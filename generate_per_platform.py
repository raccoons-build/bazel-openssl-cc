import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from common import (
    GENERATED_FILES,
    OPENSSL_VERSION,
    download_openssl,
    get_extra_tar_options,
    get_make_command,
    get_platforms,
    get_start_configure_list,
    get_tar_platform,
)

MAX_PATH_LEN_WINDOWS = 260


def main(openssl_tar_path: Path, operating_system: str, github_ref_name: str) -> None:
    version = OPENSSL_VERSION
    if github_ref_name:
        version = github_ref_name
    platform_tar_files = []
    with download_openssl(OPENSSL_VERSION, operating_system) as (
        openssl_dir,
        openssl_info,
    ):
        for platform in get_platforms(operating_system):
            write_config_file(openssl_dir, platform)
            start_configure_list = get_start_configure_list(operating_system, platform)
            subprocess.run(
                # no-dynamic-engine to prevent loading shared libraries at runtime.
                start_configure_list
                + [
                    "--config=config.conf",
                    "openssl_config",
                    "no-afalgeng",
                    "no-dynamic-engine",
                ],
                cwd=openssl_dir,
                check=True,
            )
            make_command = get_make_command(operating_system)
            subprocess.run(
                [make_command] + GENERATED_FILES,
                cwd=openssl_dir,
                # SOURCE_DATE_EPOCH lets us put a deterministic value in the DATE in generated headers
                # it needs to be non-zero
                env=dict(os.environ) | {"SOURCE_DATE_EPOCH": "443779200"},
                check=True,
            )

            # Write out the openssl_info to be used later
            with open(Path(os.path.join(openssl_dir, "openssl_info.json")), "w") as fp:
                json.dump(openssl_info, fp)
            tar = "gtar" if sys.platform == "darwin" else "tar"
            extra_tar_options = get_extra_tar_options(operating_system)

            # Each platforms version of openssl is written to its own tar
            platform_openssl_tar_path = openssl_tar_path / f"{version}.bcr.wip.{get_tar_platform(platform)}.tar.gz"
            platform_tar_files.append(str(platform_openssl_tar_path))

            # Just grab everything.
            subprocess.run(
                [tar] + extra_tar_options + ["-czf", platform_openssl_tar_path, openssl_dir],
                check=True,
            )

    tar = "gtar" if sys.platform == "darwin" else "tar"
    extra_tar_options = get_extra_tar_options(operating_system)

    all_openssl_tar_path = openssl_tar_path / f"{version}.bcr.wip.{operating_system}.tar.gz"

    # Just zip up every platform zip file
    subprocess.run(
        [tar] + extra_tar_options + ["-czf", str(all_openssl_tar_path)] + platform_tar_files,
        check=True,
    )


def move_files(openssl_dir: str, files: list[Path]) -> tuple[list[Path], str]:
    suffix = f"openssl-{OPENSSL_VERSION}"
    prefix_dir = str(openssl_dir).removesuffix(suffix)
    moved_files = [Path(str(file).removeprefix(prefix_dir)) for file in files]

    shutil.move(openssl_dir, suffix)

    return moved_files, suffix


def write_config_file(openssl_dir: Path, platform: str) -> None:
    with (openssl_dir / "config.conf").open("w") as f:
        f.write(
            f"""(
    'openssl_config' => {{
        inherit_from => [ "{platform}" ],
        dso_scheme   => undef,
    }}
);
"""
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser("bazel-openssl-cc")
    parser.add_argument("--os", required=True)
    parser.add_argument("--openssl_tar_path", type=Path, required=True)
    parser.add_argument("--github_ref_name", required=False)

    args = parser.parse_args()
    main(args.openssl_tar_path, args.os, args.github_ref_name)
