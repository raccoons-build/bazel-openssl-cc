"""Shared constants and helpers for the generation pipeline."""

import base64
import hashlib
import os
import platform
import shutil
from pathlib import Path

OPENSSL_VERSION = "3.5.5"

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


def script_dir() -> Path:
    """Return the directory containing the generator scripts and templates.

    Under ``bazel run`` the env var ``BUILD_WORKSPACE_DIRECTORY`` points to the
    real source tree (runfiles won't contain untracked data files).  For
    standalone invocations ``Path(__file__).parent`` is correct.
    """
    bwd = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if bwd:
        return Path(bwd)
    return Path(__file__).resolve().parent


def copy_from_here_to(local_path: str, dst: Path, executable: bool = False) -> None:
    dst.parent.mkdir(exist_ok=True, parents=True)
    shutil.copyfile(script_dir() / local_path, dst)
    if executable:
        if platform.system() == "Windows":
            os.access(dst, os.R_OK | os.W_OK | os.X_OK)
        else:
            os.chmod(dst, 0o755)
