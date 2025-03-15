import argparse
import os
import subprocess
import sys
import pathlib
import json
import shutil

from common import download_openssl, openssl_version, get_platforms, get_start_configure_list, get_make_command, generated_files, get_extra_tar_options, copy_from_here_to, get_simple_platform, WINDOWS

MAX_PATH_LEN_WINDOWS = 260

def main(bcr_dir: str, openssl_tar_path: str, tag: str, operating_system: str):
    openssl_module_dir = pathlib.Path(
        os.path.join(bcr_dir, "modules", "openssl"))
    out_dir = pathlib.Path(os.path.join(openssl_module_dir, tag))
    os.makedirs(out_dir)
    overlay_dir = pathlib.Path(os.path.join(out_dir, "overlay"))
    os.makedirs(overlay_dir)

    copy_from_here_to("presubmit.yml", pathlib.Path(
        os.path.join(out_dir, "presubmit.yml")))

    with download_openssl(openssl_version, out_dir, overlay_dir) as (openssl_dir, openssl_info):
        for platform in get_platforms(operating_system):
            write_config_file(openssl_dir, platform)
            start_configure_list = get_start_configure_list(operating_system, platform)
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
            
            # Write out the openssl_info to be used later
            with open(pathlib.Path(os.path.join(openssl_dir, 'openssl_info.json')), 'w') as fp:
                json.dump(openssl_info, fp)
            # Just grab every file
            all_files_to_tar, to_tar_dir = get_files_to_tar(openssl_dir)
            files_to_tar = []
            simple_platform = get_simple_platform(operating_system)
            if simple_platform == WINDOWS:
                for file in all_files_to_tar:
                    if len(str(file)) < MAX_PATH_LEN_WINDOWS: 
                        files_to_tar.append(file)
            else: 
                files_to_tar = all_files_to_tar
            subprocess.check_call(["ls" "-R", to_tar_dir])
            tar = "gtar" if sys.platform == "darwin" else "tar"
            extra_tar_options = get_extra_tar_options(operating_system)
            subprocess.check_call([tar] + extra_tar_options + ["-czf", openssl_tar_path] + files_to_tar,
                                cwd=to_tar_dir,
                                )

def move_files(openssl_dir: str, files):
    suffix = f'openssl-{openssl_version}'
    prefix_dir = str(openssl_dir).removesuffix(suffix)
    moved_files = [pathlib.Path(f"/{str(file).removeprefix(prefix_dir)}") for file in files]

    shutil.move(openssl_dir, suffix)

    return moved_files, suffix

def list_of_files_matching_pattern(openssl_dir: str, pattern: str):
    return list(sorted(pathlib.Path(openssl_dir).rglob(pattern=pattern)))

def get_files_to_tar(openssl_dir: str):

    all_files_to_tar = []

    all_files_to_tar += list_of_files_matching_pattern(openssl_dir, "openssl_info.json")
    all_files_to_tar += list_of_files_matching_pattern(openssl_dir, "configdata*")
    all_files_to_tar += list_of_files_matching_pattern(openssl_dir, "Makefile*")
    all_files_to_tar += list_of_files_matching_pattern(openssl_dir, "opensslconf.h")
    all_files_to_tar += list_of_files_matching_pattern(openssl_dir, "config.h")
    all_files_to_tar += list_of_files_matching_pattern(openssl_dir, "crypto/**/*")
    all_files_to_tar += list_of_files_matching_pattern(openssl_dir, "include/**/*")
    all_files_to_tar += list_of_files_matching_pattern(openssl_dir, "ssl/**/*")
    all_files_to_tar += list_of_files_matching_pattern(openssl_dir, "providers/**/*")
    all_files_to_tar += list_of_files_matching_pattern(openssl_dir, "apps/**/*")

    moved_files_to_tar, dst_dir = move_files(openssl_dir, all_files_to_tar)

    return list(sorted(moved_files_to_tar)), dst_dir

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

if __name__ == "__main__":
    parser = argparse.ArgumentParser("bazel-openssl-cc")
    parser.add_argument("--os", required=True)
    parser.add_argument("--bcr_dir", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--openssl_tar_path", required=True)

    args = parser.parse_args()
    main(args.bcr_dir, args.openssl_tar_path, args.tag, args.os)
