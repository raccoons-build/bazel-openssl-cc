import argparse
import os
import subprocess
import sys
import pathlib
import json

from common import download_openssl, openssl_version, get_platforms, get_start_configure_list, get_make_command, generated_files, get_extra_tar_options, copy_from_here_to

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
            
            files_to_tar = list(sorted(os.listdir(openssl_dir)))
            tar = "gtar" if sys.platform == "darwin" else "tar"
            extra_tar_options = get_extra_tar_options(operating_system)
            subprocess.check_call([tar] + extra_tar_options + ["-czf", openssl_tar_path] + files_to_tar,
                                cwd=openssl_dir,
                                )



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
