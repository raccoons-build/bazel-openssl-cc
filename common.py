"""All functions and constants shared between geneartion scripts"""

import base64
import hashlib
import os
import platform
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

OPENSSL_VERSION = "3.3.1"

MAC_ARM64 = "darwin64-arm64-cc"
MAC_X86 = "darwin64-x86_64-cc"
LINUX_ARM64 = "linux-aarch64"
LINUX_X86 = "linux-x86_64-clang"
WINDOWS_ARM64 = "VC-WIN64-CLANGASM-ARM"
WINDOWS_X86 = "VC-WIN64A-masm"

LINUX_PLATFORMS = [LINUX_ARM64, LINUX_X86]

MAC_PLATFORMS = [MAC_ARM64, MAC_X86]

UNIX_PLATFORMS = LINUX_PLATFORMS + MAC_PLATFORMS

WINDOWS_PLATFORMS = [WINDOWS_ARM64, WINDOWS_X86]

ALL_PLATFORMS = UNIX_PLATFORMS + WINDOWS_PLATFORMS

PLATFORMS_X86_64 = [MAC_X86, LINUX_X86, WINDOWS_X86]
PLATFORMS_ARM64 = [MAC_ARM64, LINUX_ARM64, WINDOWS_ARM64]

# Used for generation and testing on a pull request.
WINDOWS = "windows"
UNIX = "unix"
LINUX = "linux"
MAC = "mac"
ARM64 = "arm64"
X86_64 = "x86_64"
# Used for release flow.
ALL = "all"


GENERATED_SRCS = [
    "apps/progs.c",
    "crypto/params_idx.c",
    "providers/common/der/der_digests_gen.c",
    "providers/common/der/der_dsa_gen.c",
    "providers/common/der/der_ec_gen.c",
    "providers/common/der/der_ecx_gen.c",
    "providers/common/der/der_rsa_gen.c",
    "providers/common/der/der_sm2_gen.c",
    "providers/common/der/der_wrap_gen.c",
]

GENERATED_HDRS = [
    "apps/progs.h",
    "crypto/buildinf.h",
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
    "providers/common/include/prov/der_digests.h",
    "providers/common/include/prov/der_dsa.h",
    "providers/common/include/prov/der_ec.h",
    "providers/common/include/prov/der_ecx.h",
    "providers/common/include/prov/der_rsa.h",
    "providers/common/include/prov/der_sm2.h",
    "providers/common/include/prov/der_wrap.h",
]

GENERATED_FILES = GENERATED_SRCS + GENERATED_HDRS


def get_platforms(os: str) -> list[str]:
    if os == WINDOWS:
        return WINDOWS_PLATFORMS
    elif os == UNIX:
        return UNIX_PLATFORMS
    elif os == ALL:
        return ALL_PLATFORMS
    else:
        raise ValueError(f"Unknown os: {os}")


def get_make_command(os: str) -> str:
    if os == WINDOWS:
        return "nmake"
    elif os == UNIX:
        return "make"
    elif os == ALL:
        return "make"
    else:
        raise ValueError(f"Unknown os: {os}")


def get_start_configure_list(os: str, platform: str) -> list[str]:
    if os == WINDOWS:
        if platform in WINDOWS_PLATFORMS:
            # On Windows we don't  use any assembly because the assembler is mismatched
            # between MSVC with Bazel and MSVC with OpenSSL.
            # See https://github.com/rustls/boringssl/blob/018edfaaaeea43bf35a16e9f7ba24510c0c003bb/util/util.bzl#L149
            # for the inspiration.
            return ["perl", "Configure", "no-asm"]
        elif platform in UNIX_PLATFORMS:
            # If we are generating unix on Windows (don't know why we would) we need to keep assembly.
            return ["perl", "Configure"]
        else:
            raise ValueError(f"Unknown platform: {platform}")
    elif os == UNIX:
        return ["./Configure"]
    elif os == ALL:
        return ["./Configure"]
    else:
        raise ValueError(f"Unknown os: {os}")


def get_extra_tar_options(os: str) -> list[str]:
    all_tar_options = ["--owner", "root", "--group", "wheel", "--mtime=UTC 1980-01-01"]
    if os == WINDOWS:
        return []
    elif os == UNIX:
        return all_tar_options
    elif os == ALL:
        return all_tar_options
    else:
        raise ValueError(f"Unknown os: {os}")


def get_simple_platform(platform: str) -> str:
    if platform in WINDOWS_PLATFORMS:
        return WINDOWS
    elif platform in UNIX_PLATFORMS:
        return UNIX
    else:
        raise ValueError(f"Unknown platform: {platform}")


def get_specific_common_platform(platform: str) -> str:
    if platform in WINDOWS_PLATFORMS:
        return WINDOWS
    elif platform in LINUX_PLATFORMS:
        return LINUX
    elif platform in MAC_PLATFORMS:
        return MAC
    else:
        raise ValueError(f"Unknown platform: {platform}")


def get_architecture(platform: str) -> str:
    if platform in PLATFORMS_ARM64:
        return ARM64
    elif platform in PLATFORMS_X86_64:
        return X86_64
    else:
        raise ValueError(f"Unknown platform: {platform}")


def get_tar_platform(platform: str) -> str:
    # For now we just return platform but we want this
    # in case we change how they are output
    return platform


def get_dir_to_copy(root: Path, platform: str) -> Path:
    return Path(
        os.path.join(
            root,
            f"{get_simple_platform(platform)}_unzipped",
            get_specific_common_platform(platform),
            get_architecture(platform),
            "tmp",
        )
    )


@contextmanager
def download_openssl(version: str, simple_platform: str) -> Generator[tuple[Path, dict[str, str]], None, None]:
    prefix_dir = f"openssl-{version}"
    tempdir: Path
    try:
        tempdir = Path("/tmp")
        if simple_platform == WINDOWS:
            tempdir = Path("C:/tmp")
        if not tempdir.exists():
            tempdir.mkdir(exist_ok=True, parents=True)
        tar_path = tempdir / "openssl.tar.gz"
        url = f"https://github.com/openssl/openssl/releases/download/openssl-{version}/openssl-{version}.tar.gz"
        subprocess.run(
            ["curl", "--fail", "-L", "-o", str(tar_path), url],
            check=True,
        )
        subprocess.run(["tar", "xzf", str(tar_path)], cwd=tempdir, check=True)

        openssl_info = {
            "url": url,
            "integrity": integrity_hash(tar_path),
            "strip_prefix": prefix_dir,
        }

        yield (tempdir / prefix_dir), openssl_info
    # On Windows this step can fail and we need to retry. But first clean things up.
    except Exception as e:
        cleanup(Path(prefix_dir), tempdir)
        raise e


def cleanup(prefix_dir: Path, tempdir: Path) -> None:
    if prefix_dir.exists():
        shutil.rmtree(prefix_dir, ignore_errors=True)
    if tempdir.exists():
        shutil.rmtree(tempdir, ignore_errors=True)


def integrity_hash(path: Path) -> str:
    algo = "sha256"
    with path.open("rb") as f:
        digest = hashlib.file_digest(f, algo).digest()
    return f"{algo}-{base64.b64encode(digest).decode('utf-8')}"


def copy_from_here_to(local_path: str, dst: Path, executable: bool = False) -> None:
    dst.parent.mkdir(exist_ok=True, parents=True)
    current_file = Path(__file__).parent
    shutil.copyfile(current_file / local_path, dst)
    if executable:
        if platform.system() == "Windows":
            os.access(dst, os.R_OK | os.W_OK | os.X_OK)
        else:
            os.chmod(dst, 0o755)
