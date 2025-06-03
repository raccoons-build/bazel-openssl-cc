import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from typing import Dict

from common import (
    LINUX_X86,
    all_platforms,
    copy_from_here_to,
    generated_files,
    get_dir_to_copy,
    get_extra_tar_options,
    get_platforms,
    get_simple_platform,
    integrity_hash,
    openssl_version,
)


def replace_backslashes_in_paths(string):
    """Replaces single backslashes with double backslashes in paths within a string."""

    def replace_match(match):
        return match.group(0).replace("\\", "\\\\")

    # This pattern matches Windows-style paths (e.g., C:\Users\John\Documents)
    pattern = r"[\w\\\-.]+"

    return re.sub(pattern, replace_match, string)


def main(
    bcr_dir: str,
    overlay_tar_path: str,
    tag: str,
    buildifier_path: str,
    release_tar_url_template: str,
    operating_system: str,
    openssl_tar_path: str,
):
    openssl_module_dir = pathlib.Path(os.path.join(bcr_dir, "modules", "openssl"))
    out_dir = pathlib.Path(os.path.join(openssl_module_dir, tag))
    overlay_dir = pathlib.Path(os.path.join(out_dir, "overlay"))

    copy_from_here_to(
        "presubmit.yml", pathlib.Path(os.path.join(out_dir, "presubmit.yml"))
    )

    openssl_tar_root = pathlib.Path(openssl_tar_path)
    openssl_version_dir = pathlib.Path(
        os.path.join(openssl_tar_root, f"openssl-{openssl_version}")
    )

    generated_path_to_platform_to_contents = defaultdict(dict)
    platform_to_perl_output = {}
    for platform in get_platforms(operating_system):
        simple_platform = get_simple_platform(platform)

        # Since there are hardcoded paths in the generated config files for openssl it is easier to
        # just move the files from their platform specific subdirs to root so that the paths all work.
        dir_to_copy = get_dir_to_copy(openssl_tar_root, platform)
        dir_to_copy_with_version = os.path.join(
            dir_to_copy, f"openssl-{openssl_version}"
        )
        if os.path.exists(openssl_version_dir):
            shutil.rmtree(openssl_version_dir)
        shutil.move(dir_to_copy_with_version, openssl_tar_root)

        with open(
            pathlib.Path(os.path.join(openssl_version_dir, "openssl_info.json")), "r"
        ) as fp:
            openssl_info = json.load(fp)
            for generated_file in generated_files:
                with open(
                    pathlib.Path(os.path.join(openssl_version_dir, generated_file)), "r"
                ) as f:
                    content = f.read()
                generated_path_to_platform_to_contents[generated_file][
                    platform
                ] = content
            simple_platform = get_simple_platform(platform)
            platform_to_perl_output[platform] = subprocess.check_output(
                [
                    "perl",
                    "-I.",
                    "-l",
                    "-Mconfigdata",
                    pathlib.Path(
                        os.path.join(os.path.dirname(__file__), "extract_srcs.pl")
                    ),
                    simple_platform,
                ],
                cwd=openssl_version_dir,
            ).decode("utf-8")

        # Since we run this script multiple times we need to put the files back where they came from
        shutil.move(openssl_version_dir, dir_to_copy)

    # Since we moved all the platform specific folders away. Use a representative folder to grab the
    # platform independent files.
    platform_independent_dir = get_dir_to_copy(openssl_tar_root, LINUX_X86)
    platform_independent_dir_with_version = os.path.join(
        platform_independent_dir, f"openssl-{openssl_version}"
    )
    with tempfile.TemporaryDirectory() as output_tar_dir:
        platform_independent_generated_files = []
        platform_specific_generated_paths = []

        for (
            path,
            platform_to_contents,
        ) in generated_path_to_platform_to_contents.items():
            if len(set(platform_to_contents.values())) == 1:
                os.makedirs(
                    os.path.dirname(pathlib.Path(os.path.join(output_tar_dir, path))),
                    exist_ok=True,
                )
                shutil.copyfile(
                    pathlib.Path(
                        os.path.join(platform_independent_dir_with_version, path)
                    ),
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
                platform_to_perl_output.get(platform),
                {
                    path: generated_path_to_platform_to_contents.get(path).get(platform)
                    for path in platform_specific_generated_paths
                },
                pathlib.Path(buildifier_path),
            )

        copy_from_here_to(
            "BUILD.openssl.bazel",
            pathlib.Path(os.path.join(overlay_dir, "BUILD.bazel")),
        )
        copy_from_here_to(
            "utils.bzl", pathlib.Path(os.path.join(overlay_dir, "utils.bzl"))
        )
        copy_from_here_to(
            "collate_into_directory.bzl",
            pathlib.Path(os.path.join(output_tar_dir, "collate_into_directory.bzl")),
        )
        copy_from_here_to(
            "perl_genrule.bzl",
            pathlib.Path(os.path.join(output_tar_dir, "perl_genrule.bzl")),
        )
        copy_from_here_to(
            ".bazelrc",
            pathlib.Path(os.path.join(output_tar_dir, ".bazelrc")),
        )
        copy_from_here_to(
            "move_file_and_strip_prefix.sh",
            pathlib.Path(os.path.join(output_tar_dir, "move_file_and_strip_prefix.sh")),
            executable=True,
        )
        copy_from_here_to(
            "perl_generate_file.sh",
            pathlib.Path(os.path.join(output_tar_dir, "perl_generate_file.sh")),
            executable=True,
        )
        with open(pathlib.Path(os.path.join(output_tar_dir, "common.bzl")), "w") as f:
            f.write(
                f"COMMON_GENERATED_FILES = {json.dumps(platform_independent_generated_files)}\n"
            )

        copy_from_here_to(
            "BUILD.test.bazel",
            pathlib.Path(os.path.join(overlay_dir, "test_bazel_build", "BUILD.bazel")),
        )
        copy_from_here_to(
            "sha256_test.py",
            pathlib.Path(
                os.path.join(overlay_dir, "test_bazel_build", "sha256_test.py")
            ),
            executable=True,
        )

        with open(pathlib.Path(os.path.join(output_tar_dir, "BUILD.bazel")), "w") as f:
            f.write('exports_files(glob(["**"]))\n')

        files_to_tar = list(sorted(os.listdir(output_tar_dir)))
        tar = "gtar" if sys.platform == "darwin" else "tar"
        extra_tar_options = get_extra_tar_options(operating_system)
        subprocess.check_call(
            [tar] + extra_tar_options + ["-czf", overlay_tar_path] + files_to_tar,
            cwd=output_tar_dir,
        )

        write_module_files(
            out_dir,
            tag,
            release_tar_url_template.format(tag=tag),
            integrity_hash(overlay_tar_path),
        )

        write_source_json(out_dir, openssl_info)

    add_to_metadata(openssl_module_dir, tag)


def ignore_files(dir, files):
    # Some unneeded files cause permissions issues
    return [file for file in files if str(file).endswith((".rev", ".idx"))]


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

bazel_dep(name = "platforms", version = "0.0.11")
bazel_dep(name = "rules_cc", version = "0.1.1")
bazel_dep(name = "rules_perl", version = "0.4.1")
bazel_dep(name = "rules_python", version = "1.2.0")

http_archive = use_repo_rule("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

http_archive(
    name = "openssl-generated-overlay",
    integrity = "{overlay_archive_integrity}",
    url = "{overlay_archive_url}",
)
"""
        )
    overlay_module_path = os.path.join(out_dir, "overlay", "MODULE.bazel")
    if not os.path.exists(overlay_module_path):
        os.symlink("../MODULE.bazel", pathlib.Path(overlay_module_path))


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

    json_dump = json.dumps(
        platform_specific_generated_files, indent="    ", sort_keys=True
    )

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


def add_to_metadata(openssl_module_dir, tag):
    metadata_path = pathlib.Path(os.path.join(openssl_module_dir, "metadata.json"))
    with open(metadata_path, "r") as f:
        content = json.load(f)
    content["versions"].append(tag)
    to_save = json.dumps(content, sort_keys=True, indent="  ") + "\n"
    with open(metadata_path, "w") as f:
        f.write(to_save)


if __name__ == "__main__":
    parser = argparse.ArgumentParser("bazel-openssl-cc")
    parser.add_argument("--os", required=True)
    parser.add_argument("--bcr_dir", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--overlay_tar_path", required=True)
    parser.add_argument("--openssl_tar_path", required=True)
    parser.add_argument(
        "--release_tar_url_template",
        default="https://github.com/raccoons-build/bazel-openssl-cc/releases/download/{tag}/bazel-openssl-cc-{tag}.tar.gz",
    )
    parser.add_argument("--buildifier", default="buildifier")
    args = parser.parse_args()
    main(
        args.bcr_dir,
        args.overlay_tar_path,
        args.tag,
        args.buildifier,
        args.release_tar_url_template,
        args.os,
        args.openssl_tar_path,
    )
