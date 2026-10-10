"""Shared constants and helpers for the generation pipeline."""

import base64
import hashlib
import json
import os
import platform
import re
import shutil
from pathlib import Path
from typing import NamedTuple

# Repository layout (all paths relative to the repo root):
#   generator/  the generation scripts and their input templates
#   overlay/    copied verbatim into the BCR overlay, same layout
#   pregen/     copied verbatim into the root of the pre-generated archive
#   versions/   per-OpenSSL-version overrides of any of the above (see versions/README.md)
GENERATOR_DIR = "generator"
OVERLAY_DIR = "overlay"
PREGEN_DIR = "pregen"
VERSIONS_DIR = "versions"

MAC_ARM64 = "darwin64-arm64-cc"
MAC_X86 = "darwin64-x86_64-cc"
LINUX_ARM64 = "linux-aarch64"
LINUX_X86 = "linux-x86_64-clang"
LINUX_RISCV64 = "linux64-riscv64"
LINUX_PPC64LE = "linux-ppc64le"
LINUX_S390X = "linux64-s390x"
LINUX_ARM = "linux-armv4"
WINDOWS_ARM64 = "VC-WIN64-CLANGASM-ARM"
WINDOWS_X86 = "VC-WIN64A-masm"
ANDROID_ARM64 = "android-arm64"
ANDROID_X86 = "android-x86_64"
IOS_ARM64 = "ios64-cross"
FREEBSD_X86 = "BSD-x86_64"
FREEBSD_ARM64 = "BSD-aarch64"

LINUX_PLATFORMS = [LINUX_ARM64, LINUX_X86, LINUX_RISCV64, LINUX_PPC64LE, LINUX_S390X, LINUX_ARM]
MAC_PLATFORMS = [MAC_ARM64, MAC_X86]
UNIX_PLATFORMS = LINUX_PLATFORMS + MAC_PLATFORMS
WINDOWS_PLATFORMS = [WINDOWS_ARM64, WINDOWS_X86]
ANDROID_PLATFORMS = [ANDROID_ARM64, ANDROID_X86]
IOS_PLATFORMS = [IOS_ARM64]
FREEBSD_PLATFORMS = [FREEBSD_ARM64, FREEBSD_X86]
ALL_PLATFORMS = UNIX_PLATFORMS + WINDOWS_PLATFORMS + ANDROID_PLATFORMS + IOS_PLATFORMS + FREEBSD_PLATFORMS

NO_ASM_TARGET = "no-asm"

# config_name → (os, cpu) constraint labels for Bazel config_setting targets.
PLATFORM_CONSTRAINTS: dict[str, tuple[str, str]] = {
    "darwin_arm64": ("@platforms//os:macos", "@platforms//cpu:arm64"),
    "darwin_x86_64": ("@platforms//os:macos", "@platforms//cpu:x86_64"),
    "linux_aarch64": ("@platforms//os:linux", "@platforms//cpu:aarch64"),
    "linux_x86_64": ("@platforms//os:linux", "@platforms//cpu:x86_64"),
    "linux_riscv64": ("@platforms//os:linux", "@platforms//cpu:riscv64"),
    "linux_ppc64le": ("@platforms//os:linux", "@platforms//cpu:ppc64le"),
    "linux_s390x": ("@platforms//os:linux", "@platforms//cpu:s390x"),
    "linux_arm": ("@platforms//os:linux", "@platforms//cpu:arm"),
    "windows_arm64": ("@platforms//os:windows", "@platforms//cpu:arm64"),
    "windows_x64": ("@platforms//os:windows", "@platforms//cpu:x86_64"),
    "android_arm64": ("@platforms//os:android", "@platforms//cpu:arm64"),
    "android_x86_64": ("@platforms//os:android", "@platforms//cpu:x86_64"),
    "ios_arm64": ("@platforms//os:ios", "@platforms//cpu:arm64"),
    "freebsd_x86_64": ("@platforms//os:freebsd", "@platforms//cpu:x86_64"),
    "freebsd_aarch64": ("@platforms//os:freebsd", "@platforms//cpu:aarch64"),
}

_CONFIG_NAME_MAP = {
    MAC_ARM64: "darwin_arm64",
    MAC_X86: "darwin_x86_64",
    LINUX_ARM64: "linux_aarch64",
    LINUX_X86: "linux_x86_64",
    LINUX_RISCV64: "linux_riscv64",
    LINUX_PPC64LE: "linux_ppc64le",
    LINUX_S390X: "linux_s390x",
    LINUX_ARM: "linux_arm",
    WINDOWS_ARM64: "windows_arm64",
    WINDOWS_X86: "windows_x64",
    ANDROID_ARM64: "android_arm64",
    ANDROID_X86: "android_x86_64",
    IOS_ARM64: "ios_arm64",
    FREEBSD_X86: "freebsd_x86_64",
    FREEBSD_ARM64: "freebsd_aarch64",
    NO_ASM_TARGET: "no_asm",
}


def get_simple_config_name(platform: str) -> str:
    """Map a Configure target name to a Bazel config_setting name."""
    return _CONFIG_NAME_MAP[platform]


def get_configure_target(platform: str) -> str:
    """Return the OpenSSL Configure target string.

    For the no-asm fallback, we use a generic linux target since we only
    need the C source list (assembly is disabled).
    """
    if platform == NO_ASM_TARGET:
        return "linux-x86_64-clang"
    return platform


def integrity_hash(path: Path) -> str:
    algo = "sha256"
    with path.open("rb") as f:
        digest = hashlib.file_digest(f, algo).digest()
    return f"{algo}-{base64.b64encode(digest).decode('utf-8')}"


def repo_root() -> Path:
    """Return the root of this repository (the parent of generator/, overlay/, ...).

    Under ``bazel run`` the env var ``BUILD_WORKSPACE_DIRECTORY`` points to the
    real source tree (runfiles won't contain the overlay files, which Bazel
    ignores via .bazelignore). For standalone invocations this file lives in
    ``<root>/generator/``.
    """
    bwd = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if bwd:
        return Path(bwd)
    return Path(__file__).resolve().parent.parent


class OpenSSLVersion(NamedTuple):
    """OpenSSL version as declared by ``VERSION.dat`` in the source tree."""

    major: int
    minor: int
    patch: int
    pre_release_tag: str = ""

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @property
    def archive_name(self) -> str:
        """Upstream release archive base name (also the strip_prefix)."""
        return f"openssl-{self}"

    @property
    def source_url(self) -> str:
        return f"https://github.com/openssl/openssl/releases/download/{self.archive_name}/{self.archive_name}.tar.gz"

    def override_selectors(self) -> list[str]:
        """Names of the ``versions/`` directories that apply to this version, most specific first."""
        return [
            f"{self.major}.{self.minor}.{self.patch}",
            f"{self.major}.{self.minor}",
            f"{self.major}",
        ]

    @classmethod
    def from_source_tree(cls, openssl_dir: Path) -> "OpenSSLVersion":
        """Read ``VERSION.dat`` from an OpenSSL 3.0+ source tree."""
        version_dat = openssl_dir / "VERSION.dat"
        if not version_dat.is_file():
            raise RuntimeError(
                f"{version_dat} not found; --openssl_source_dir must point at the root of an "
                "OpenSSL 3.0+ source tree (the directory containing Configure and VERSION.dat)"
            )
        fields: dict[str, str] = {}
        for line in version_dat.read_text().splitlines():
            m = re.fullmatch(r"\s*(\w+)\s*=\s*(.*?)\s*", line)
            if m:
                fields[m.group(1)] = m.group(2).strip('"')
        try:
            return cls(
                int(fields["MAJOR"]),
                int(fields["MINOR"]),
                int(fields["PATCH"]),
                fields.get("PRE_RELEASE_TAG", ""),
            )
        except (KeyError, ValueError) as e:
            raise RuntimeError(f"Could not parse {version_dat}: {e}") from e


# Any directory under versions/ must be named like one of override_selectors().
_SELECTOR_RE = re.compile(r"\d+(\.\d+){0,2}")


def add_to_metadata(openssl_module_dir: Path, tag: str) -> None:
    """Register ``tag`` in the BCR module's metadata.json (idempotent)."""
    metadata_path = openssl_module_dir / "metadata.json"
    with open(metadata_path, "r") as f:
        content = json.load(f)
    if tag not in content["versions"]:
        content["versions"].append(tag)
    with open(metadata_path, "w") as f:
        f.write(json.dumps(content, sort_keys=True, indent="  ") + "\n")


class OverlaySources:
    """Resolves repo files, honouring per-version overrides.

    A repo-relative path such as ``overlay/BUILD.bazel`` is looked up in
    ``versions/<MAJOR.MINOR.PATCH>/``, then ``versions/<MAJOR.MINOR>/``, then
    ``versions/<MAJOR>/``, and finally the repo root itself. The first match
    wins, so an override directory only needs to contain the files that differ
    for that version.
    """

    def __init__(self, root: Path, version: OpenSSLVersion):
        self.root = root
        self._search_dirs = [root / VERSIONS_DIR / s for s in version.override_selectors()] + [root]

    def resolve(self, local_path: str) -> Path:
        for d in self._search_dirs:
            candidate = d / local_path
            if candidate.is_file():
                return candidate
        raise FileNotFoundError(f"{local_path} not found in {self.root} or any applicable versions/ override")

    def read_text(self, local_path: str) -> str:
        return self.resolve(local_path).read_text()

    def copy_to(self, local_path: str, dst: Path, executable: bool = False) -> None:
        src = self.resolve(local_path)
        dst.parent.mkdir(exist_ok=True, parents=True)
        shutil.copyfile(src, dst)
        if executable:
            if platform.system() == "Windows":
                os.access(dst, os.R_OK | os.W_OK | os.X_OK)
            else:
                os.chmod(dst, 0o755)

    def tree_files(self, rel_dir: str) -> list[str]:
        """All repo-relative file paths under ``rel_dir``, across the root and applicable overrides.

        Overrides may add files to a tree (not just replace them), so this is a union.
        """
        found: set[str] = set()
        for d in self._search_dirs:
            base = d / rel_dir
            if not base.is_dir():
                continue
            for f in base.rglob("*"):
                if f.is_file():
                    found.add(f.relative_to(d).as_posix())
        return sorted(found)

    def copy_tree(self, rel_dir: str, dst: Path) -> None:
        """Copy every file under ``rel_dir`` (with overrides applied) to ``dst``, preserving layout."""
        for rel in self.tree_files(rel_dir):
            self.copy_to(rel, dst / Path(rel).relative_to(rel_dir))

    def overrides_in_effect(self) -> list[Path]:
        """Override directories that exist for this version, most specific first (lookup order)."""
        return [d for d in self._search_dirs[:-1] if d.is_dir()]

    def validate_overrides(self) -> None:
        """Sanity-check the versions/ tree.

        Every directory there must be named like a version selector, files may
        only live under the known trees (generator/, overlay/, pregen/), and
        generator inputs must replace an existing file. Anything else is almost
        always a typo that would otherwise be silently ignored.
        """
        versions_dir = self.root / VERSIONS_DIR
        if versions_dir.is_dir():
            for d in versions_dir.iterdir():
                if d.is_dir() and not _SELECTOR_RE.fullmatch(d.name):
                    raise RuntimeError(
                        f"{d}: override directories must be named MAJOR, MAJOR.MINOR or MAJOR.MINOR.PATCH"
                    )
        for d in self.overrides_in_effect():
            for f in d.rglob("*"):
                if not f.is_file() or f == d / "README.md":
                    continue
                rel = f.relative_to(d)
                top = rel.parts[0]
                if top not in (GENERATOR_DIR, OVERLAY_DIR, PREGEN_DIR):
                    raise RuntimeError(
                        f"{f}: override files must live under {GENERATOR_DIR}/, {OVERLAY_DIR}/ or {PREGEN_DIR}/"
                    )
                if top == GENERATOR_DIR and not (self.root / rel).is_file():
                    raise RuntimeError(f"{f} overrides {rel}, but {self.root / rel} does not exist")
