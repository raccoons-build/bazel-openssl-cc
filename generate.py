import argparse
import base64
from collections import defaultdict
import hashlib
import json
import os

from contextlib import contextmanager
import shutil
import subprocess
import sys
import tempfile
from typing import Dict

openssl_version = "3.3.1"

nix_platforms = [
    "darwin64-arm64-cc",
    "darwin64-x86_64-cc",
    "linux-x86_64-clang",
    "linux-aarch64",
]

windows_platforms = ["VC-WIN64A",
                     "VC-WIN64-ARM"]

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


def get_platforms(os: str):
    if os == 'windows':
        return windows_platforms
    elif os == 'nix':
        return nix_platforms
    else:
        raise ValueError(f'Unknown os: {os}')


def get_start_configure_list(os: str):
    if os == 'windows':
        return ["perl", "Configure"]
    elif os == 'nix':
        return ["./Configure"]
    else:
        raise ValueError(f'Unknown os: {os}')


def get_make_command(os: str):
    if os == 'windows':
        return "nmake"
    elif os == 'nix':
        return "make"
    else:
        raise ValueError(f'Unknown os: {os}')


def main(bcr_dir: str, overlay_tar_path: str, tag: str, buildifier_path: str, release_tar_url_template: str, operating_system: str):
    openssl_module_dir = os.path.join(bcr_dir, "modules", "openssl")
    out_dir = os.path.join(openssl_module_dir, tag)
    os.makedirs(out_dir)
    overlay_dir = os.path.join(out_dir, "overlay")
    os.makedirs(overlay_dir)

    copy_from_here_to("presubmit.yml", os.path.join(out_dir, "presubmit.yml"))

    with download_openssl(openssl_version) as (openssl_dir, openssl_info):
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
                with open(os.path.join(openssl_dir, generated_file), "r") as f:
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
                    os.path.join(os.path.dirname(__file__), "extract_srcs.pl"),
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
                        os.path.dirname(os.path.join(output_tar_dir, path)),
                        exist_ok=True,
                    )
                    shutil.copyfile(
                        os.path.join(openssl_dir, path),
                        os.path.join(output_tar_dir, path),
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
                    buildifier_path,
                )

            copy_from_here_to(
                "BUILD.openssl.bazel", os.path.join(overlay_dir, "BUILD.bazel")
            )
            copy_from_here_to("utils.bzl", os.path.join(
                overlay_dir, "utils.bzl"))
            copy_from_here_to(
                "collate_into_directory.bzl",
                os.path.join(output_tar_dir, "collate_into_directory.bzl"),
            )
            copy_from_here_to(
                "move_file_and_strip_prefix.sh",
                os.path.join(output_tar_dir, "move_file_and_strip_prefix.sh"),
                executable=True,
            )

            with open(os.path.join(output_tar_dir, "common.bzl"), "w") as f:
                f.write(
                    f"COMMON_GENERATED_FILES = {json.dumps(platform_independent_generated_files)}\n"
                )

            copy_from_here_to(
                "BUILD.test.bazel",
                os.path.join(overlay_dir, "test_bazel_build", "BUILD.bazel"),
            )

            with open(os.path.join(output_tar_dir, "BUILD.bazel"), "w") as f:
                f.write('exports_files(glob(["**"]))\n')

            files_to_tar = list(sorted(os.listdir(output_tar_dir)))
            tar = "gtar" if sys.platform == "darwin" else "tar"
            subprocess.check_call(
                [
                    tar,
                    "--owner",
                    "root",
                    "--group",
                    "wheel",
                    "--mtime=UTC 1980-01-01",
                    "-czf",
                    overlay_tar_path,
                ]
                + files_to_tar,
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
def download_openssl(version: str):
    with tempfile.TemporaryDirectory() as tempdir:
        tar_path = os.path.join(tempdir, "openssl.tar.gz")
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

        yield os.path.join(tempdir, prefix_dir), openssl_info


def write_module_files(
    out_dir: str,
    tag: int,
    overlay_archive_url: str,
    overlay_archive_integrity: str,
):
    module_bazel_path = os.path.join(out_dir, "MODULE.bazel")
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

http_archive = use_repo_rule("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

http_archive(
    name = "openssl-generated-overlay",
    integrity = "{overlay_archive_integrity}",
    url = "{overlay_archive_url}",
)
"""
        )
    os.symlink("../MODULE.bazel",
               os.path.join(out_dir, "overlay", "MODULE.bazel"))


def write_source_json(out_dir: str, openssl_info: Dict):
    overlay_info = {}
    overlay_dir = os.path.join(out_dir, "overlay")
    for root, _, files in os.walk(overlay_dir):
        for file in files:
            full_path = os.path.join(root, file)
            overlay_relative_path = os.path.relpath(full_path, overlay_dir)
            overlay_info[overlay_relative_path] = integrity_hash(full_path)
    openssl_info["overlay"] = overlay_info
    with open(os.path.join(out_dir, "source.json"), "w") as f:
        f.write(json.dumps(openssl_info, indent="    ", sort_keys=True) + "\n")


def integrity_hash(path: str) -> str:
    algo = "sha256"
    with open(path, "rb") as f:
        digest = hashlib.file_digest(f, algo).digest()
    return f"{algo}-{base64.b64encode(digest).decode('utf-8')}"


def write_config_file(openssl_dir, platform):
    with open(os.path.join(openssl_dir, "config.conf"), "w") as f:
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
PERLASM_TOOLS = []
        """
    out = f"""# Generated code. DO NOT EDIT.

PLATFORM = "{platform}"
OPENSSL_VERSION = "{openssl_version}"

{perl_output}

GEN_FILES = {json_dump}
""" 
    # Buildifier thinks that Windows paths are escape sequences.
    if "WIN" in platform:
        out = out.replace("\\", "\\\\")
        print(out)
    path = os.path.join(overlay_dir, f"constants-{platform}.bzl")
    with open(path, "w") as f:
        f.write(out)
    subprocess.check_call([buildifier_path, path])


def copy_from_here_to(local_path: str, dst: str, executable: bool = False):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(os.path.join(os.path.dirname(__file__), local_path), dst)
    if executable:
        os.chmod(dst, 0o755)


def add_to_metadata(openssl_module_dir, tag):
    metadata_path = os.path.join(openssl_module_dir, "metadata.json")
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
    previous_dir = os.path.join(openssl_module_dir, previous_tag)
    if not os.path.exists(previous_dir):
        return None
    return previous_dir


def dedupe_content_with_symlinks(previous_tag_dir, out_dir):
    for root, _, files in os.walk(out_dir):
        for file in files:
            full_path = os.path.join(root, file)
            module_relative_path = os.path.relpath(full_path, out_dir)
            old_path = os.path.join(previous_tag_dir, module_relative_path)
            old_hash = integrity_hash(old_path)
            new_path = os.path.join(out_dir, module_relative_path)
            new_hash = integrity_hash(new_path)
            if old_hash == new_hash:
                link_target = os.path.relpath(
                    old_path, os.path.dirname(new_path))
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
