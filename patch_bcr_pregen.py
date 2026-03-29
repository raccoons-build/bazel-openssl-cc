"""Patch BCR module files after the pregen tarball is finalized.

Computes the integrity hash of the pregen tarball, patches the
PLACEHOLDER in MODULE.bazel, optionally overrides the download URL
(for local CI testing with file:// paths), and recomputes all overlay
file hashes in source.json.
"""

import argparse
import base64
import hashlib
import json
import os
import re
from pathlib import Path


def integrity_hash(path: Path) -> str:
    with path.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").digest()
    return "sha256-" + base64.b64encode(digest).decode()


def patch_module_bazel(path: Path, integrity: str, url_override: str | None) -> None:
    text = path.read_text()
    text = text.replace('integrity = "PLACEHOLDER"', f'integrity = "{integrity}"')
    if url_override:
        text = re.sub(
            r'"https://github\.com/raccoons-build/bazel-openssl-cc/releases/download/[^"]*"',
            f'"{url_override}"',
            text,
        )
    path.write_text(text)


def recompute_overlay_hashes(bcr_dir: Path, tag: str) -> None:
    overlay_dir = bcr_dir / "modules" / "openssl" / tag / "overlay"
    source_json_path = bcr_dir / "modules" / "openssl" / tag / "source.json"

    with open(source_json_path) as f:
        sj = json.load(f)

    sj["overlay"] = {}
    for root, _, files in os.walk(overlay_dir):
        for fn in files:
            full = Path(root) / fn
            rel = os.path.relpath(full, overlay_dir)
            sj["overlay"][rel] = integrity_hash(full)

    with open(source_json_path, "w") as f:
        json.dump(sj, f, indent="    ", sort_keys=True)
        f.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tarball", required=True, help="Path to the pregen tarball")
    parser.add_argument("--bcr_dir", required=True, help="Path to the bazel-central-registry checkout")
    parser.add_argument("--tag", required=True, help="Version tag (e.g. 3.5.5.bcr.1)")
    parser.add_argument(
        "--url_override", default=None, help="Override the pregen download URL (e.g. file:///tmp/pregen.tar.gz)"
    )
    args = parser.parse_args()

    tarball = Path(args.tarball)
    bcr_dir = Path(args.bcr_dir)
    tag = args.tag

    integrity = integrity_hash(tarball)
    print(f"Pregen integrity: {integrity}")

    module_dir = bcr_dir / "modules" / "openssl" / tag
    for module_path in [module_dir / "MODULE.bazel", module_dir / "overlay" / "MODULE.bazel"]:
        if module_path.exists():
            patch_module_bazel(module_path, integrity, args.url_override)
            print(f"Patched {module_path}")

    recompute_overlay_hashes(bcr_dir, tag)
    print(f"Recomputed overlay hashes in source.json")


if __name__ == "__main__":
    main()
