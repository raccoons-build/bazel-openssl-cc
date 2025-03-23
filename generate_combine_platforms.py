import argparse
from collections import defaultdict
import json
import os
import re

import shutil
import subprocess
import sys
import tempfile
import pathlib
from typing import Dict

from common import copy_from_here_to, openssl_version, get_platforms, generated_files, get_simple_platform, all_platforms, get_extra_tar_options, integrity_hash, get_dir_to_copy

def replace_backslashes_in_paths(string):
    """Replaces single backslashes with double backslashes in paths within a string."""

    def replace_match(match):
        return match.group(0).replace('\\', '\\\\')

    # This pattern matches Windows-style paths (e.g., C:\Users\John\Documents)
    pattern = r'[\w\\\-.]+'

    return re.sub(pattern, replace_match, string)


def main(bcr_dir: str, tag: str, buildifier_path: str, operating_system: str, openssl_tar_path: str, github_ref_name: str):
    openssl_module_dir = pathlib.Path(
        os.path.join(bcr_dir, "modules", "openssl"))
    out_dir = pathlib.Path(os.path.join(openssl_module_dir, tag))

    version = openssl_version
    if github_ref_name: 
        version = github_ref_name

    copy_from_here_to("presubmit.yml", pathlib.Path(
        os.path.join(out_dir, "presubmit.yml")))

    openssl_tar_root = pathlib.Path(openssl_tar_path)
    openssl_version_dir = pathlib.Path(os.path.join(openssl_tar_root, f'openssl-{openssl_version}'))
    
    generated_path_to_platform_to_contents = defaultdict(dict)
    platform_to_perl_output = {}
    for platform in get_platforms(operating_system):
        simple_platform = get_simple_platform(platform)

        dir_to_copy = get_dir_to_copy(openssl_tar_root, platform)
        dir_to_copy_with_version = os.path.join(dir_to_copy, f'openssl-{openssl_version}')
        if os.path.exists(openssl_version_dir):
            shutil.rmtree(openssl_version_dir)
        shutil.move(dir_to_copy_with_version, openssl_tar_root)

        with open(pathlib.Path(os.path.join(openssl_version_dir, 'openssl_info.json')), 'r') as fp: 
            openssl_info = json.load(fp)
            for generated_file in generated_files:
                with open(pathlib.Path(os.path.join(openssl_version_dir, generated_file)), "r") as f:
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
                    pathlib.Path(os.path.join(
                        os.path.dirname(__file__), "extract_srcs.pl")),
                    simple_platform,
                ],
                cwd=openssl_version_dir,
            ).decode("utf-8")
    with tempfile.TemporaryDirectory() as tmp_dir:
        output_tar_dir = pathlib.Path(os.path.join(tmp_dir, out_dir))
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
                    pathlib.Path(os.path.join(openssl_version_dir, path)),
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
                    path: generated_path_to_platform_to_contents.get(
                        path).get(platform)
                    for path in platform_specific_generated_paths
                },
                pathlib.Path(buildifier_path),
            )

        copy_from_here_to(
            "BUILD.openssl.bazel", pathlib.Path(
                os.path.join(output_tar_dir, "BUILD.bazel"))
        )
        copy_from_here_to("utils.bzl", pathlib.Path(os.path.join(
            output_tar_dir, "utils.bzl")))
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
            ".bazelrc",
            pathlib.Path(os.path.join(output_tar_dir,
                            ".bazelrc")),
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
        with open(pathlib.Path(os.path.join(output_tar_dir, "common.bzl")), "w") as f:
            f.write(
                f"COMMON_GENERATED_FILES = {json.dumps(platform_independent_generated_files)}\n"
            )

        copy_from_here_to(
            "BUILD.test.bazel",
            pathlib.Path(os.path.join(
                output_tar_dir, "test_bazel_build", "BUILD.bazel")),
        )
        copy_from_here_to(
            "sha256_test.py",
            pathlib.Path(os.path.join(
                output_tar_dir, "test_bazel_build", "sha256_test.py")),
            executable=True,
        )

        write_module_files(
            out_dir,
            output_tar_dir,
            tag
        )

        files_to_tar = list(sorted(os.listdir(output_tar_dir)))
        tar = "gtar" if sys.platform == "darwin" else "tar"
        extra_tar_options = get_extra_tar_options(operating_system)
        output_tar_file = os.path.join(openssl_tar_path, f'{version}.bcr.wip.tar.gz')
        subprocess.check_call([tar] + extra_tar_options + ["-czvf", output_tar_file] + files_to_tar,
                                cwd=output_tar_dir,
                                )

        write_source_json(out_dir, openssl_info)

    previous_tag_dir = guess_previous_tag_dir(openssl_module_dir, tag)
    if previous_tag_dir:
        dedupe_content_with_symlinks(previous_tag_dir, out_dir)

    add_to_metadata(openssl_module_dir, tag)

def ignore_files(dir, files):
    # Some unneeded files cause permissions issues
    return [file for file in files if str(file).endswith((".rev", ".idx"))]

def write_module_files(
    out_dir: str,
    output_tar_dir: str,
    tag: int
):
    main_module_bazel_path = pathlib.Path(os.path.join(out_dir, "MODULE.bazel"))
    with open(main_module_bazel_path, "w") as f:
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
"""
        )

    test_dir = pathlib.Path(os.path.join(output_tar_dir, "test_bazel_build"))
    if not os.path.exists(test_dir):
        os.makedirs(test_dir)
    test_module_bazel_path = pathlib.Path(os.path.join(test_dir, "MODULE.bazel"))
    with open(test_module_bazel_path, "w") as f:
        f.write(
            f"""module(name = "openssl.test")

bazel_dep(name = "rules_python", version = "1.2.0")
bazel_dep(name = "rules_cc", version = "0.0.13")
bazel_dep(name = "openssl")

local_path_override(
    module_name = "openssl",
    path = "..",
)
"""
        )


def write_source_json(out_dir: str, openssl_info: Dict):
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
    output_dir: str,
    openssl_version: str,
    platform: str,
    perl_output: str,
    platform_specific_generated_files: Dict[str, str],
    buildifier_path: str,
):

    json_dump = json.dumps(platform_specific_generated_files,
                           indent="    ", sort_keys=True)

    # Buildifier thinks that Windows paths are escape sequences.
    if "WIN" in platform:
        perl_output = replace_backslashes_in_paths(perl_output)
    out = f"""# Generated code. DO NOT EDIT.

PLATFORM = "{platform}"
OPENSSL_VERSION = "{openssl_version}"

{perl_output}

GEN_FILES = {json_dump}
""" 
    path = pathlib.Path(os.path.join(output_dir, f"constants-{platform}.bzl"))
    with open(pathlib.Path(path), "w") as f:
        f.write(out)
    subprocess.check_call([pathlib.Path(buildifier_path), pathlib.Path(path)])

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
    parser.add_argument("--openssl_tar_path", required=True)
    parser.add_argument("--github_ref_name", required=False)
    parser.add_argument("--buildifier", default="buildifier")
    args = parser.parse_args()
    main(args.bcr_dir, args.tag,
         args.buildifier, args.os, args.openssl_tar_path, args.github_ref_name)
