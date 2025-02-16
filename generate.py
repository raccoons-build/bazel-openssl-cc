import argparse
import base64
from collections import defaultdict
import hashlib
import json
import os
import re

from contextlib import contextmanager
import shutil
import subprocess
import sys
import tempfile
import pathlib
import platform
from typing import Dict

openssl_version = "3.3.1"

nix_platforms = [
    "darwin64-arm64-cc",
    "darwin64-x86_64-cc",
    "linux-x86_64-clang",
    "linux-aarch64",
]

windows_platforms = ["VC-WIN64A",
                     "VC-WIN64-CLANGASM-ARM"]

all_platforms = nix_platforms + windows_platforms

generated_files = [
    "apps/progs.c",
    "apps/progs.h",
    "crypto/buildinf.h",
    "crypto/params_idx.c",
    "include/crypto/bn_conf.h",
    "include/crypto/dso_conf.h",
    "include/internal/param_names.h",
    "include/openssl/asn1.h",
    "include/openssl/asn1t.h",
    "include/openssl/bio.h",
    "include/openssl/cmp.h",
    "include/openssl/cms.h",
    "include/openssl/conf.h",
    "include/openssl/configuration.h",
    "include/openssl/core_names.h",
    "include/openssl/crmf.h",
    "include/openssl/crypto.h",
    "include/openssl/ct.h",
    "include/openssl/err.h",
    "include/openssl/ess.h",
    "include/openssl/fipskey.h",
    "include/openssl/lhash.h",
    "include/openssl/ocsp.h",
    "include/openssl/opensslconf.h",
    "include/openssl/opensslv.h",
    "include/openssl/pkcs12.h",
    "include/openssl/pkcs7.h",
    "include/openssl/safestack.h",
    "include/openssl/srp.h",
    "include/openssl/ssl.h",
    "include/openssl/ui.h",
    "include/openssl/x509.h",
    "include/openssl/x509_vfy.h",
    "include/openssl/x509v3.h",
    "providers/common/der/der_digests_gen.c",
    "providers/common/der/der_dsa_gen.c",
    "providers/common/der/der_ec_gen.c",
    "providers/common/der/der_ecx_gen.c",
    "providers/common/der/der_rsa_gen.c",
    "providers/common/der/der_sm2_gen.c",
    "providers/common/der/der_wrap_gen.c",
    "providers/common/include/prov/der_digests.h",
    "providers/common/include/prov/der_dsa.h",
    "providers/common/include/prov/der_ec.h",
    "providers/common/include/prov/der_ecx.h",
    "providers/common/include/prov/der_rsa.h",
    "providers/common/include/prov/der_sm2.h",
    "providers/common/include/prov/der_wrap.h",
]

# Used for generation and testing on a pull request.
WINDOWS = "windows"
NIX = "nix"
# Used for release flow.
ALL = "all"


def get_platforms(os: str):
    if os == WINDOWS:
        return windows_platforms
    elif os == NIX:
        return nix_platforms
    elif os == ALL:
        return all_platforms
    else:
        raise ValueError(f'Unknown os: {os}')


def get_start_configure_list(os: str):
    if os == WINDOWS:
        return ["perl", "Configure"]
    elif os == NIX:
        return ["./Configure"]
    elif os == ALL:
        return ["./Configure"]
    else:
        raise ValueError(f'Unknown os: {os}')


def get_make_command(os: str):
    if os == WINDOWS:
        return "nmake"
    elif os == NIX:
        return "make"
    elif os == ALL:
        return "make"
    else:
        raise ValueError(f'Unknown os: {os}')


def get_extra_tar_options(os: str):
    all_tar_options = ["--owner",
                       "root",
                       "--group",
                       "wheel",
                       "--mtime=UTC 1980-01-01"]
    if os == WINDOWS:
        return []
    elif os == NIX:
        return all_tar_options
    elif os == ALL:
        return all_tar_options
    else:
        raise ValueError(f'Unknown os: {os}')


def replace_backslashes_in_paths(string):
    """Replaces single backslashes with double backslashes in paths within a string."""

    def replace_match(match):
        return match.group(0).replace('\\', '\\\\')

    # This pattern matches Windows-style paths (e.g., C:\Users\John\Documents)
    pattern = r'[\w\\\-.]+'

    return re.sub(pattern, replace_match, string)


def main(bcr_dir: str, overlay_tar_path: str, tag: str, buildifier_path: str, release_tar_url_template: str, operating_system: str):
    openssl_module_dir = pathlib.Path(
        os.path.join(bcr_dir, "modules", "openssl"))
    out_dir = pathlib.Path(os.path.join(openssl_module_dir, tag))
    os.makedirs(out_dir)
    overlay_dir = pathlib.Path(os.path.join(out_dir, "overlay"))
    os.makedirs(overlay_dir)

    copy_from_here_to("presubmit.yml", pathlib.Path(
        os.path.join(out_dir, "presubmit.yml")))

    with download_openssl(openssl_version, out_dir, overlay_dir) as (openssl_dir, openssl_info):
        generated_path_to_platform_to_contents = defaultdict(dict)
        platform_to_perl_output = {}
        for platform in get_platforms(operating_system):
            write_config_file(openssl_dir, platform)
            start_configure_list = get_start_configure_list(operating_system)
            subprocess.check_call(
                # no-dynamic-engine to prevent loading shared libraries at runtime.
                start_configure_list +
                [
                    "--config=config.conf",
                    "openssl_config",
                    "no-afalgeng",
                    "no-dynamic-engine",
                ],
                cwd=openssl_dir,
            )
            make_command = get_make_command(operating_system)
            subprocess.check_call(
                [make_command] + generated_files,
                cwd=openssl_dir,
                # SOURCE_DATE_EPOCH lets us put a deterministic value in the DATE in generated headers
                # it needs to be non-zero
                env=dict(os.environ) | {"SOURCE_DATE_EPOCH": "443779200"},
            )
            for generated_file in generated_files:
                with open(pathlib.Path(os.path.join(openssl_dir, generated_file)), "r") as f:
                    content = f.read()
                generated_path_to_platform_to_contents[generated_file][
                    platform
                ] = content
            platform_to_perl_output[platform] = subprocess.check_output(
                [
                    "perl",
                    "-I.",
                    "-l",
                    "-Mconfigdata",
                    pathlib.Path(os.path.join(
                        os.path.dirname(__file__), "extract_srcs.pl")),
                ],
                cwd=openssl_dir,
            ).decode("utf-8")

        with tempfile.TemporaryDirectory() as output_tar_dir:
            platform_independent_generated_files = []
            platform_specific_generated_paths = []

            for (
                path,
                platform_to_contents,
            ) in generated_path_to_platform_to_contents.items():
                if len(set(platform_to_contents.values())) == 1:
                    os.makedirs(
                        os.path.dirname(pathlib.Path(
                            os.path.join(output_tar_dir, path))),
                        exist_ok=True,
                    )
                    shutil.copyfile(
                        pathlib.Path(os.path.join(openssl_dir, path)),
                        pathlib.Path(os.path.join(output_tar_dir, path)),
                    )
                    platform_independent_generated_files.append(path)
                else:
                    platform_specific_generated_paths.append(path)

            # We need to write constants for ALL platforms not just the ones we are configuring openssl
            # for so the BUILD file imports work
            for platform in all_platforms:
                write_platform_specific_constants(
                    output_tar_dir,
                    openssl_version,
                    platform,
                    # There should be no perl output when we aren't generating for a platform.
                    platform_to_perl_output.get(platform, ""),
                    {
                        # If there is no path or platform then return nothing
                        path: generated_path_to_platform_to_contents.get(
                            path, {}).get(platform, "")
                        for path in platform_specific_generated_paths
                    },
                    pathlib.Path(buildifier_path),
                )

            copy_from_here_to(
                "BUILD.openssl.bazel", pathlib.Path(
                    os.path.join(overlay_dir, "BUILD.bazel"))
            )
            copy_from_here_to("utils.bzl", pathlib.Path(os.path.join(
                overlay_dir, "utils.bzl")))
            copy_from_here_to(
                "collate_into_directory.bzl",
                pathlib.Path(os.path.join(output_tar_dir,
                             "collate_into_directory.bzl")),
            )
            copy_from_here_to(
                "perl_genrule.bzl",
                pathlib.Path(os.path.join(output_tar_dir,
                             "perl_genrule.bzl")),
            )
            copy_from_here_to(
                "move_file_and_strip_prefix.sh",
                pathlib.Path(os.path.join(output_tar_dir,
                             "move_file_and_strip_prefix.sh")),
                executable=True,
            )
            copy_from_here_to(
                "perl_generate_file.sh",
                pathlib.Path(os.path.join(output_tar_dir,
                             "perl_generate_file.sh")),
                executable=True,
            )
            copy_from_here_to(
                "perl_generate_file.ps1",
                pathlib.Path(os.path.join(output_tar_dir,
                             "perl_generate_file.ps1")),
                executable=True,
            )
            with open(pathlib.Path(os.path.join(output_tar_dir, "common.bzl")), "w") as f:
                f.write(
                    f"COMMON_GENERATED_FILES = {json.dumps(platform_independent_generated_files)}\n"
                )

            copy_from_here_to(
                "BUILD.test.bazel",
                pathlib.Path(os.path.join(
                    overlay_dir, "test_bazel_build", "BUILD.bazel")),
            )

            with open(pathlib.Path(os.path.join(output_tar_dir, "BUILD.bazel")), "w") as f:
                f.write('exports_files(glob(["**"]))\n')

            files_to_tar = list(sorted(os.listdir(output_tar_dir)))
            tar = "gtar" if sys.platform == "darwin" else "tar"
            extra_tar_options = get_extra_tar_options(operating_system)
            subprocess.check_call([tar] + extra_tar_options + ["-czf", overlay_tar_path] + files_to_tar,
                                  cwd=output_tar_dir,
                                  )

            write_module_files(
                out_dir,
                tag,
                release_tar_url_template.format(tag=tag),
                integrity_hash(overlay_tar_path),
            )

        write_source_json(out_dir, openssl_info)

        previous_tag_dir = guess_previous_tag_dir(openssl_module_dir, tag)
        if previous_tag_dir:
            dedupe_content_with_symlinks(previous_tag_dir, out_dir)

    add_to_metadata(openssl_module_dir, tag)


@contextmanager
def download_openssl(version: str, out_dir: str, overlay_dir: str):
    with tempfile.TemporaryDirectory() as tempdir:
        try:
            tar_path = pathlib.Path(os.path.join(tempdir, "openssl.tar.gz"))
            url = f"https://github.com/openssl/openssl/releases/download/openssl-{version}/openssl-{version}.tar.gz"
            subprocess.check_call(
                ["curl", "--fail", "-L", "-o", tar_path, url],
            )
            subprocess.check_call(["tar", "xzf", tar_path], cwd=tempdir)

            prefix_dir = f"openssl-{version}"
            openssl_info = {
                "url": url,
                "integrity": integrity_hash(tar_path),
                "strip_prefix": prefix_dir,
            }

            yield pathlib.Path(os.path.join(tempdir, prefix_dir)), openssl_info
        # On Windows this step can fail and we need to retry. But first clean things up.
        except Exception as e:
            cleanup(
                out_dir, overlay_dir)
            raise e


def cleanup(out_dir: str, overlay_dir: str):
    if os.path.exists(out_dir):
        os.removedirs(out_dir)
    if os.path.exists(overlay_dir):
        os.removedirs(overlay_dir)


def write_module_files(
    out_dir: str,
    tag: int,
    overlay_archive_url: str,
    overlay_archive_integrity: str,
):
    module_bazel_path = pathlib.Path(os.path.join(out_dir, "MODULE.bazel"))
    with open(module_bazel_path, "w") as f:
        f.write(
            f"""module(
    name = "openssl",
    version = "{tag}",
    # Note: This should rarely change. For now, we hold it as a constant.
    # Realistically, we should only change it if the major version of openssl changes.
    # When that happens, we probably want to change this to a single-digit number representing that version number.
    compatibility_level = 3030100,
)

bazel_dep(name = "platforms", version = "0.0.10")
bazel_dep(name = "rules_cc", version = "0.0.13")
bazel_dep(name = "rules_perl", version = "0.2.4")
bazel_dep(name = "toolchains_llvm", version = "1.3.0")

# Configure and register the toolchain.
llvm = use_extension("@toolchains_llvm//toolchain/extensions:llvm.bzl", "llvm")
llvm.toolchain(
   llvm_version = "16.0.0",
)

use_repo(llvm, "llvm_toolchain")

register_toolchains("@llvm_toolchain//:all")

http_archive = use_repo_rule("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

http_archive(
    name = "openssl-generated-overlay",
    integrity = "{overlay_archive_integrity}",
    url = "{overlay_archive_url}",
)
"""
        )
    os.symlink("../MODULE.bazel",
               pathlib.Path(os.path.join(out_dir, "overlay", "MODULE.bazel")))


def write_source_json(out_dir: str, openssl_info: Dict):
    overlay_info = {}
    overlay_dir = pathlib.Path(os.path.join(out_dir, "overlay"))
    for root, _, files in os.walk(overlay_dir):
        for file in files:
            full_path = pathlib.Path(os.path.join(root, file))
            overlay_relative_path = os.path.relpath(full_path, overlay_dir)
            overlay_info[overlay_relative_path] = integrity_hash(full_path)
    openssl_info["overlay"] = overlay_info
    with open(pathlib.Path(os.path.join(out_dir, "source.json")), "w") as f:
        f.write(json.dumps(openssl_info, indent="    ", sort_keys=True) + "\n")


def integrity_hash(path: str) -> str:
    algo = "sha256"
    with open(pathlib.Path(path).resolve(), "rb") as f:
        digest = hashlib.file_digest(f, algo).digest()
    return f"{algo}-{base64.b64encode(digest).decode('utf-8')}"


def write_config_file(openssl_dir, platform):
    with open(pathlib.Path(os.path.join(openssl_dir, "config.conf")), "w") as f:
        f.write(
            f"""(
    'openssl_config' => {{
        inherit_from => [ "{platform}" ],
        dso_scheme   => undef,
    }}
);
"""
        )


def write_platform_specific_constants(
    overlay_dir: str,
    openssl_version: str,
    platform: str,
    perl_output: str,
    platform_specific_generated_files: Dict[str, str],
    buildifier_path: str,
):

    json_dump = json.dumps(platform_specific_generated_files,
                           indent="    ", sort_keys=True)
    # If there are no platform specific generated files then just make empty lists.
    if not perl_output:
        perl_output = """
LIBCRYPTO_DEFINES = []
LIBCRYPTO_SRCS = []
LIBSSL_DEFINES = []
LIBSSL_SRCS = []
OPENSSL_APP_SRCS = []
OPENSSL_DEFINES = []
PERLASM_GEN = ''
PERLASM_OUTS = []
PERLASM_TOOLS = []
        """
    # Buildifier thinks that Windows paths are escape sequences.
    if "WIN" in platform:
        perl_output = replace_backslashes_in_paths(perl_output)
    out = f"""# Generated code. DO NOT EDIT.

PLATFORM = "{platform}"
OPENSSL_VERSION = "{openssl_version}"

{perl_output}

GEN_FILES = {json_dump}
""" 
    path = pathlib.Path(os.path.join(overlay_dir, f"constants-{platform}.bzl"))
    with open(pathlib.Path(path), "w") as f:
        f.write(out)
    subprocess.check_call([pathlib.Path(buildifier_path), pathlib.Path(path)])


def copy_from_here_to(local_path: str, dst: str, executable: bool = False):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(pathlib.Path(os.path.join(
        os.path.dirname(__file__), local_path)), dst)
    if executable:
        if platform.system == "Windows":
            os.access(dst, os.R_OK | os.W_OK | os.X_OK)
        else:
            os.chmod(dst, 0o755)

def add_to_metadata(openssl_module_dir, tag):
    metadata_path = pathlib.Path(os.path.join(
        openssl_module_dir, "metadata.json"))
    with open(metadata_path, "r") as f:
        content = json.load(f)
    content["versions"].append(tag)
    to_save = json.dumps(content, sort_keys=True, indent="  ") + "\n"
    with open(metadata_path, "w") as f:
        f.write(to_save)


def guess_previous_tag_dir(openssl_module_dir, tag):
    parts = tag.split(".")
    if len(parts) < 2:
        return None
    if parts[-2] != "bcr":
        return None
    try:
        bcr_iteration = int(parts[-1])
    except:
        return None
    if bcr_iteration < 1:
        return None
    previous_tag = ".".join(parts[:-1] + [f"{bcr_iteration - 1}"])
    previous_dir = pathlib.Path(os.path.join(openssl_module_dir, previous_tag))
    if not os.path.exists(previous_dir):
        return None
    return previous_dir


def dedupe_content_with_symlinks(previous_tag_dir, out_dir):
    for root, _, files in os.walk(out_dir):
        for file in files:
            full_path = pathlib.Path(os.path.join(root, file))
            module_relative_path = pathlib.Path(
                os.path.relpath(full_path, out_dir))
            old_path = pathlib.Path(os.path.join(
                previous_tag_dir, module_relative_path))
            old_hash = integrity_hash(old_path)
            new_path = pathlib.Path(os.path.join(
                out_dir, module_relative_path))
            new_hash = integrity_hash(new_path)
            if old_hash == new_hash:
                link_target = pathlib.Path(os.path.relpath(
                    old_path, os.path.dirname(new_path)))
                os.unlink(new_path)
                os.symlink(link_target, new_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser("bazel-openssl-cc")
    parser.add_argument("--os", required=True)
    parser.add_argument("--bcr_dir", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--overlay_tar_path", required=True)
    parser.add_argument(
        "--release_tar_url_template",
        default="https://github.com/raccoons-build/bazel-openssl-cc/releases/download/{tag}/bazel-openssl-cc-{tag}.tar.gz",
    )
    parser.add_argument("--buildifier", default="buildifier")
    args = parser.parse_args()
    main(args.bcr_dir, args.overlay_tar_path, args.tag,
         args.buildifier, args.release_tar_url_template, args.os)
