import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from textwrap import dedent
from typing import NamedTuple

from common import (
    GENERATED_FILES,
    LINUX_X86,
    OPENSSL_VERSION,
    copy_from_here_to,
    get_dir_to_copy,
    get_extra_tar_options,
    get_platforms,
    get_simple_platform,
    integrity_hash,
)


class PerlData(NamedTuple):
    """Platform-specific data extracted from OpenSSL configuration."""

    libcrypto_srcs: list[str]
    libcrypto_hdrs: list[str]
    libcrypto_generated_srcs: list[str]
    libcrypto_generated_hdrs: list[str]
    libssl_srcs: list[str]
    libssl_hdrs: list[str]
    libssl_generated_srcs: list[str]
    libssl_generated_hdrs: list[str]
    openssl_app_srcs: list[str]
    openssl_app_hdrs: list[str]
    openssl_app_generated_srcs: list[str]
    openssl_app_generated_hdrs: list[str]
    perlasm_outs: list[str]
    perlasm_tools: list[str]
    perlasm_gen_commands: list[str]
    libcrypto_defines: list[str]
    libssl_defines: list[str]
    openssl_app_defines: list[str]
    openssl_defines: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, list[str]]) -> "PerlData":
        """Create PerlData from a dictionary, deduplicating and sorting list fields."""
        return cls(
            libcrypto_srcs=data["libcrypto_srcs"],
            libcrypto_hdrs=data["libcrypto_hdrs"],
            libcrypto_generated_srcs=data["libcrypto_generated_srcs"],
            libcrypto_generated_hdrs=data["libcrypto_generated_hdrs"],
            libssl_srcs=data["libssl_srcs"],
            libssl_hdrs=data["libssl_hdrs"],
            libssl_generated_srcs=data["libssl_generated_srcs"],
            libssl_generated_hdrs=data["libssl_generated_hdrs"],
            openssl_app_srcs=data["openssl_app_srcs"],
            openssl_app_hdrs=data["openssl_app_hdrs"],
            openssl_app_generated_srcs=data["openssl_app_generated_srcs"],
            openssl_app_generated_hdrs=data["openssl_app_generated_hdrs"],
            perlasm_outs=sorted(set(data["perlasm_outs"])),
            perlasm_tools=sorted(set(data["perlasm_tools"])),
            perlasm_gen_commands=sorted(set(data["perlasm_gen_commands"])),
            libcrypto_defines=sorted(set(data["libcrypto_defines"])),
            libssl_defines=sorted(set(data["libssl_defines"])),
            openssl_app_defines=sorted(set(data["openssl_app_defines"])),
            openssl_defines=sorted(set(data["openssl_defines"])),
        )


def main(
    bcr_dir: str,
    overlay_tar_path: str,
    tag: str,
    buildifier_path: str,
    release_tar_url_template: str,
    operating_system: str,
    openssl_tar_path: str,
) -> None:
    openssl_module_dir = Path(os.path.join(bcr_dir, "modules", "openssl"))
    out_dir = Path(os.path.join(openssl_module_dir, tag))
    overlay_dir = Path(os.path.join(out_dir, "overlay"))

    copy_from_here_to("presubmit.yml", out_dir / "presubmit.yml")

    openssl_tar_root = Path(openssl_tar_path)
    openssl_version_dir = openssl_tar_root / f"openssl-{OPENSSL_VERSION}"

    platform_to_perl_data, generated_path_to_platform_to_contents, openssl_info = extract_all_platforms_data(
        openssl_tar_root, openssl_version_dir, operating_system
    )

    # Since we moved all the platform specific folders away. Use a representative folder to grab the
    # platform independent files.
    platform_independent_dir = get_dir_to_copy(openssl_tar_root, LINUX_X86)
    platform_independent_dir_with_version = os.path.join(platform_independent_dir, f"openssl-{OPENSSL_VERSION}")
    with tempfile.TemporaryDirectory() as output_tar_dir_str:
        output_tar_dir = Path(output_tar_dir_str)
        platform_independent_generated_files = []
        platform_specific_generated_paths = []

        for (
            path,
            platform_to_contents,
        ) in generated_path_to_platform_to_contents.items():
            if len(set(platform_to_contents.values())) == 1:
                os.makedirs(
                    os.path.dirname(Path(os.path.join(output_tar_dir, path))),
                    exist_ok=True,
                )
                shutil.copyfile(
                    Path(os.path.join(platform_independent_dir_with_version, path)),
                    Path(os.path.join(output_tar_dir, path)),
                )
                platform_independent_generated_files.append(path)
            else:
                platform_specific_generated_paths.append(path)

        # Separate common generated files into srcs and hdrs
        common_generated_srcs = sorted([f for f in platform_independent_generated_files if f.endswith(".c")])
        common_generated_hdrs = sorted([f for f in platform_independent_generated_files if f.endswith(".h")])

        # Write constants for the platforms we configured
        for platform in platform_to_perl_data.keys():
            write_platform_specific_constants(
                str(output_tar_dir),
                OPENSSL_VERSION,
                platform,
                platform_to_perl_data[platform],
                {
                    path: generated_path_to_platform_to_contents[path][platform]
                    for path in platform_specific_generated_paths
                },
                common_generated_srcs,
                common_generated_hdrs,
            )

        copy_from_here_to(
            "BUILD.openssl.bazel",
            overlay_dir / "BUILD.bazel",
        )
        copy_from_here_to("utils.bzl", overlay_dir / "utils.bzl")
        copy_from_here_to(
            "collate_into_directory.bzl",
            output_tar_dir / "collate_into_directory.bzl",
        )
        copy_from_here_to(
            "perl_genrule.bzl",
            output_tar_dir / "perl_genrule.bzl",
        )
        copy_from_here_to(
            ".bazelrc",
            output_tar_dir / ".bazelrc",
        )
        copy_from_here_to(
            "move_file_and_strip_prefix.sh",
            output_tar_dir / "move_file_and_strip_prefix.sh",
            executable=True,
        )
        copy_from_here_to(
            "move_file_and_strip_prefix.bat",
            output_tar_dir / "move_file_and_strip_prefix.bat",
            executable=True,
        )

        copy_from_here_to(
            "BUILD.configs.bazel",
            overlay_dir / "configs" / "BUILD.bazel",
        )

        copy_from_here_to(
            "BUILD.test.bazel",
            overlay_dir / "test_bazel_build" / "BUILD.bazel",
        )
        copy_from_here_to(
            "sha256_test.cc",
            overlay_dir / "test_bazel_build" / "sha256_test.cc",
        )

        copy_from_here_to(
            "build_test.cc",
            overlay_dir / "test_bazel_build" / "build_test.cc",
        )

        with (output_tar_dir / "BUILD.bazel").open("w") as f:
            f.write(
                dedent(
                    """\
                exports_files(glob(["**"]))

                filegroup(
                    name = "move_file_and_strip_prefix",
                    srcs = select({
                        "@platforms//os:windows": ["move_file_and_strip_prefix.bat"],
                        "//conditions:default": ["move_file_and_strip_prefix.sh"],
                    }),
                )
                """
                )
            )

        # Format the entire directory.
        subprocess.run(
            [str(buildifier_path), "-lint=fix", "-mode=fix", "-r", str(output_tar_dir)],
            check=True,
        )

        files_to_tar = sorted(os.listdir(output_tar_dir))
        tar = "gtar" if sys.platform == "darwin" else "tar"
        extra_tar_options = get_extra_tar_options(operating_system)
        subprocess.run(
            [tar] + extra_tar_options + ["-czf", overlay_tar_path] + files_to_tar,
            cwd=str(output_tar_dir),
            check=True,
        )

        write_module_files(
            out_dir,
            tag,
            release_tar_url_template.format(tag=tag),
            integrity_hash(Path(overlay_tar_path)),
        )

        write_source_json(out_dir, openssl_info)

    add_to_metadata(openssl_module_dir, tag)


def ignore_files(dir: str, files: list[str]) -> list[str]:
    # Some unneeded files cause permissions issues
    return [file for file in files if str(file).endswith((".rev", ".idx"))]


def write_module_files(
    out_dir: Path,
    tag: str,
    overlay_archive_url: str,
    overlay_archive_integrity: str,
) -> None:
    module_bazel_path = Path(os.path.join(out_dir, "MODULE.bazel"))
    with open(module_bazel_path, "w") as f:
        f.write(
            f"""\
module(
    name = "openssl",
    version = "{tag}",
    # We use overlay, which requires at least 7.2.1
    bazel_compatibility = [">=7.2.1"],
    # Note: This should rarely change. For now, we hold it as a constant.
    # Realistically, we should only change it if the major version of openssl changes.
    # When that happens, we probably want to change this to a single-digit number representing that version number.
    compatibility_level = 3030100,
)

bazel_dep(name = "platforms", version = "1.0.0")
bazel_dep(name = "rules_cc", version = "0.2.4")
bazel_dep(name = "rules_perl", version = "0.5.0")
bazel_dep(name = "bazel_skylib", version = "1.8.2")

http_archive = use_repo_rule("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

http_archive(
    name = "openssl-generated-overlay",
    integrity = "{overlay_archive_integrity}",
    url = "{overlay_archive_url}",
)
"""
        )
    overlay_module_path = out_dir / "overlay/MODULE.bazel"
    if not overlay_module_path.exists():
        os.symlink("../MODULE.bazel", overlay_module_path)


def write_source_json(out_dir: Path, openssl_info: dict[str, str | dict[str, str]]) -> None:
    overlay_info: dict[str, str] = {}
    overlay_dir = out_dir / "overlay"
    for root, _, files in os.walk(overlay_dir):
        for file in files:
            full_path = Path(os.path.join(root, file))
            overlay_relative_path = os.path.relpath(full_path, overlay_dir)
            overlay_info[overlay_relative_path] = integrity_hash(full_path)
    openssl_info["overlay"] = overlay_info
    with (out_dir / "source.json").open("w") as f:
        f.write(json.dumps(openssl_info, indent="    ", sort_keys=True) + "\n")


def extract_all_platforms_data(
    openssl_tar_root: Path,
    openssl_version_dir: Path,
    operating_system: str,
) -> tuple[dict[str, PerlData], dict[str, dict[str, str]], dict[str, str | dict[str, str]]]:
    """Extract data for all platforms in the operating system.

    Returns:
        tuple of (platform_to_perl_data, generated_path_to_platform_to_contents, openssl_info)
    """
    platform_to_perl_data: dict[str, PerlData] = {}
    generated_path_to_platform_to_contents: dict[str, dict[str, str]] = defaultdict(dict)
    openssl_info: dict[str, str | dict[str, str]] = {}

    for platform in get_platforms(operating_system):
        perl_data, generated_file_contents, platform_openssl_info = extract_platform_data(
            openssl_tar_root, openssl_version_dir, platform
        )

        platform_to_perl_data[platform] = perl_data
        for generated_file, content in generated_file_contents.items():
            generated_path_to_platform_to_contents[generated_file][platform] = content

        # Store openssl_info from the last platform (they should all be the same)
        openssl_info = platform_openssl_info

    return platform_to_perl_data, generated_path_to_platform_to_contents, openssl_info


def extract_platform_data(
    openssl_tar_root: Path,
    openssl_version_dir: Path,
    platform: str,
) -> tuple[PerlData, dict[str, str], dict[str, str | dict[str, str]]]:
    """Extract platform-specific data by running Perl script and reading generated files.

    Returns:
        tuple of (perl_data, generated_file_contents, openssl_info)
    """
    dir_to_copy = get_dir_to_copy(openssl_tar_root, platform)
    dir_to_copy_with_version = dir_to_copy / f"openssl-{OPENSSL_VERSION}"

    # Move platform-specific directory to root
    if openssl_version_dir.exists():
        shutil.rmtree(openssl_version_dir)
    shutil.move(dir_to_copy_with_version, openssl_tar_root)

    try:
        # Read openssl_info.json
        with (openssl_version_dir / "openssl_info.json").open("r") as fp:
            openssl_info = json.load(fp)

        # Read generated files
        generated_file_contents = {}
        for generated_file in GENERATED_FILES:
            with (openssl_version_dir / generated_file).open("r") as f:
                generated_file_contents[generated_file] = f.read()

        # Run Perl script to extract sources and defines
        simple_platform = get_simple_platform(platform)
        proc_result = subprocess.run(
            [
                "perl",
                "-I.",
                "-l",
                "-Mconfigdata",
                str(Path(__file__).parent / "extract_srcs.pl"),
                simple_platform,
            ],
            cwd=openssl_version_dir,
            stdout=subprocess.PIPE,
            check=True,
        )
        perl_data_dict = json.loads(proc_result.stdout.decode("utf-8"))
        perl_data = PerlData.from_dict(perl_data_dict)

        return perl_data, generated_file_contents, openssl_info
    finally:
        # Always move directory back to its original location
        shutil.move(openssl_version_dir, dir_to_copy)


def write_config_file(openssl_dir: Path, platform: str) -> None:
    with open(Path(os.path.join(openssl_dir, "config.conf")), "w") as f:
        f.write(
            f"""(
    'openssl_config' => {{
        inherit_from => [ "{platform}" ],
        dso_scheme   => undef,
    }}
);
"""
        )


PLATFORM_CONSTANTS_TEMPLATE = """# Generated code. DO NOT EDIT.

PLATFORM = "{platform}"
OPENSSL_VERSION = "{openssl_version}"

LIBCRYPTO_SRCS = {libcrypto_srcs}

LIBCRYPTO_HDRS = {libcrypto_hdrs}

LIBSSL_SRCS = {libssl_srcs}

LIBSSL_HDRS = {libssl_hdrs}

OPENSSL_APP_SRCS = {openssl_app_srcs}

OPENSSL_APP_HDRS = {openssl_app_hdrs}

PERLASM_OUTS = {perlasm_outs}

PERLASM_TOOLS = {perlasm_tools}

PERLASM_GEN = "\\n".join({perlasm_gen})

LIBCRYPTO_DEFINES = {libcrypto_defines}

LIBSSL_DEFINES = {libssl_defines}

OPENSSL_APP_DEFINES = {openssl_app_defines}

OPENSSL_DEFINES = {openssl_defines}

# Platform-independent generated files (without ':' prefix for excludes)
COMMON_GENERATED_FILES = {common_generated_files}

GEN_FILES = {gen_files}
"""


def write_platform_specific_constants(
    overlay_dir: str,
    openssl_version: str,
    platform: str,
    perl_data: PerlData,
    platform_specific_generated_files: dict[str, str],
    common_generated_srcs: list[str],
    common_generated_hdrs: list[str],
) -> None:
    # Build the srcs/hdrs by combining regular and generated files
    libcrypto_srcs = perl_data.libcrypto_srcs + [":" + s for s in perl_data.libcrypto_generated_srcs]
    libcrypto_hdrs = perl_data.libcrypto_hdrs + [":" + h for h in perl_data.libcrypto_generated_hdrs]
    libssl_srcs = perl_data.libssl_srcs + [":" + s for s in perl_data.libssl_generated_srcs]
    libssl_hdrs = perl_data.libssl_hdrs + [":" + h for h in perl_data.libssl_generated_hdrs]
    openssl_app_srcs = perl_data.openssl_app_srcs + [":" + s for s in perl_data.openssl_app_generated_srcs]
    openssl_app_hdrs = perl_data.openssl_app_hdrs + [":" + h for h in perl_data.openssl_app_generated_hdrs]

    # Add common generated sources (with ":" prefix) if not already present
    # Create sets of existing items to check for duplicates (created once and reused)
    existing_libcrypto_srcs = set(libcrypto_srcs)
    existing_libcrypto_hdrs = set(libcrypto_hdrs)
    existing_libssl_hdrs = set(libssl_hdrs)
    existing_openssl_app_srcs = set(openssl_app_srcs)
    existing_openssl_app_hdrs = set(openssl_app_hdrs)

    for src in common_generated_srcs:
        src_with_prefix = ":" + src
        # Distribute sources based on their path
        if "apps/" in src:
            # App-specific sources
            if src not in existing_openssl_app_srcs and src_with_prefix not in existing_openssl_app_srcs:
                openssl_app_srcs.append(src_with_prefix)
                existing_openssl_app_srcs.add(src_with_prefix)
        else:
            # Default to libcrypto
            if src not in existing_libcrypto_srcs and src_with_prefix not in existing_libcrypto_srcs:
                libcrypto_srcs.append(src_with_prefix)
                existing_libcrypto_srcs.add(src_with_prefix)

    for hdr in common_generated_hdrs:
        hdr_with_prefix = ":" + hdr
        # Headers in include/openssl are needed by all libraries
        if "include/openssl/" in hdr or "include/crypto/" in hdr or "include/internal/" in hdr:
            # Add to libcrypto (most common)
            if hdr not in existing_libcrypto_hdrs and hdr_with_prefix not in existing_libcrypto_hdrs:
                libcrypto_hdrs.append(hdr_with_prefix)
                existing_libcrypto_hdrs.add(hdr_with_prefix)
            # Also add to libssl if it's a general include/openssl header
            if "include/openssl/" in hdr:
                if hdr not in existing_libssl_hdrs and hdr_with_prefix not in existing_libssl_hdrs:
                    libssl_hdrs.append(hdr_with_prefix)
                    existing_libssl_hdrs.add(hdr_with_prefix)
                if hdr not in existing_openssl_app_hdrs and hdr_with_prefix not in existing_openssl_app_hdrs:
                    openssl_app_hdrs.append(hdr_with_prefix)
                    existing_openssl_app_hdrs.add(hdr_with_prefix)
        elif "apps/" in hdr:
            # App-specific headers
            if hdr not in existing_openssl_app_hdrs and hdr_with_prefix not in existing_openssl_app_hdrs:
                openssl_app_hdrs.append(hdr_with_prefix)
                existing_openssl_app_hdrs.add(hdr_with_prefix)
        else:
            # Default to libcrypto
            if hdr not in existing_libcrypto_hdrs and hdr_with_prefix not in existing_libcrypto_hdrs:
                libcrypto_hdrs.append(hdr_with_prefix)
                existing_libcrypto_hdrs.add(hdr_with_prefix)

    # Add platform-specific generated files to appropriate lists
    # Distribute based on file path patterns
    for gen_file in platform_specific_generated_files.keys():
        gen_file_with_prefix = ":" + gen_file

        if gen_file.endswith(".h"):
            # Headers in include/openssl are needed by all libraries
            if "include/openssl/" in gen_file or "include/crypto/" in gen_file or "include/internal/" in gen_file:
                # Add to libcrypto
                if gen_file not in existing_libcrypto_hdrs and gen_file_with_prefix not in existing_libcrypto_hdrs:
                    libcrypto_hdrs.append(gen_file_with_prefix)
                    existing_libcrypto_hdrs.add(gen_file_with_prefix)
                # Also add to libssl and openssl_app if it's a general include/openssl header
                if "include/openssl/" in gen_file:
                    if gen_file not in existing_libssl_hdrs and gen_file_with_prefix not in existing_libssl_hdrs:
                        libssl_hdrs.append(gen_file_with_prefix)
                        existing_libssl_hdrs.add(gen_file_with_prefix)
                    if (
                        gen_file not in existing_openssl_app_hdrs
                        and gen_file_with_prefix not in existing_openssl_app_hdrs
                    ):
                        openssl_app_hdrs.append(gen_file_with_prefix)
                        existing_openssl_app_hdrs.add(gen_file_with_prefix)
            elif "ssl/" in gen_file and "crypto/" not in gen_file:
                # SSL-specific header
                if gen_file not in existing_libssl_hdrs and gen_file_with_prefix not in existing_libssl_hdrs:
                    libssl_hdrs.append(gen_file_with_prefix)
                    existing_libssl_hdrs.add(gen_file_with_prefix)
            elif "apps/" in gen_file:
                # App-specific header
                if gen_file not in existing_openssl_app_hdrs and gen_file_with_prefix not in existing_openssl_app_hdrs:
                    openssl_app_hdrs.append(gen_file_with_prefix)
                    existing_openssl_app_hdrs.add(gen_file_with_prefix)
            else:
                # Default to libcrypto (most common case)
                if gen_file not in existing_libcrypto_hdrs and gen_file_with_prefix not in existing_libcrypto_hdrs:
                    libcrypto_hdrs.append(gen_file_with_prefix)
                    existing_libcrypto_hdrs.add(gen_file_with_prefix)
        elif gen_file.endswith(".c"):
            # Generated .c files
            if "apps/" in gen_file:
                # App-specific sources
                if gen_file not in existing_openssl_app_srcs and gen_file_with_prefix not in existing_openssl_app_srcs:
                    openssl_app_srcs.append(gen_file_with_prefix)
                    existing_openssl_app_srcs.add(gen_file_with_prefix)
            else:
                # Default to libcrypto
                if gen_file not in existing_libcrypto_srcs and gen_file_with_prefix not in existing_libcrypto_srcs:
                    libcrypto_srcs.append(gen_file_with_prefix)
                    existing_libcrypto_srcs.add(gen_file_with_prefix)

    # Validation: Check that all GEN_FILES and common generated files are in at least one list
    all_files = set(libcrypto_srcs + libcrypto_hdrs + libssl_srcs + libssl_hdrs + openssl_app_srcs + openssl_app_hdrs)

    # Check platform-specific generated files
    for gen_file in platform_specific_generated_files.keys():
        gen_file_with_prefix = ":" + gen_file
        if gen_file not in all_files and gen_file_with_prefix not in all_files:
            print(
                f"WARNING: Platform-specific GEN_FILE {gen_file} not found in any source/header list for platform {platform}"
            )

    # Check common generated files
    for src in common_generated_srcs:
        src_with_prefix = ":" + src
        if src not in all_files and src_with_prefix not in all_files:
            print(f"WARNING: Common generated source {src} not found in any source/header list for platform {platform}")

    for hdr in common_generated_hdrs:
        hdr_with_prefix = ":" + hdr
        if hdr not in all_files and hdr_with_prefix not in all_files:
            print(f"WARNING: Common generated header {hdr} not found in any source/header list for platform {platform}")

    indent = " " * 4

    # Format all data
    out = PLATFORM_CONSTANTS_TEMPLATE.format(
        platform=platform,
        openssl_version=openssl_version,
        libcrypto_srcs=json.dumps(sorted(set(libcrypto_srcs)), indent=indent),
        libcrypto_hdrs=json.dumps(sorted(set(libcrypto_hdrs)), indent=indent),
        libssl_srcs=json.dumps(sorted(set(libssl_srcs)), indent=indent),
        libssl_hdrs=json.dumps(sorted(set(libssl_hdrs)), indent=indent),
        openssl_app_srcs=json.dumps(sorted(set(openssl_app_srcs)), indent=indent),
        openssl_app_hdrs=json.dumps(sorted(set(openssl_app_hdrs)), indent=indent),
        perlasm_outs=json.dumps(perl_data.perlasm_outs, indent=indent),
        perlasm_tools=json.dumps(perl_data.perlasm_tools, indent=indent),
        perlasm_gen=json.dumps(perl_data.perlasm_gen_commands, indent=indent),
        libcrypto_defines=json.dumps(perl_data.libcrypto_defines, indent=indent),
        libssl_defines=json.dumps(perl_data.libssl_defines, indent=indent),
        openssl_app_defines=json.dumps(perl_data.openssl_app_defines, indent=indent),
        openssl_defines=json.dumps(perl_data.openssl_defines, indent=indent),
        common_generated_files=json.dumps(sorted(common_generated_srcs + common_generated_hdrs), indent=indent),
        gen_files=json.dumps(platform_specific_generated_files, indent=indent, sort_keys=True),
    )

    path = Path(os.path.join(overlay_dir, f"constants-{platform}.bzl"))
    with open(Path(path), "w") as f:
        f.write(out)


def add_to_metadata(openssl_module_dir: Path, tag: str) -> None:
    metadata_path = Path(os.path.join(openssl_module_dir, "metadata.json"))
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
