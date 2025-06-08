"""All functions and constants shared between geneartion scripts"""

import base64
import hashlib
import os
import pathlib
import platform
import shutil
import subprocess
from contextlib import contextmanager

openssl_version = "3.3.1"

MAC_ARM64 = "darwin64-arm64-cc"
MAC_X86 = "darwin64-x86_64-cc"
LINUX_ARM64 = "linux-aarch64"
LINUX_X86 = "linux-x86_64-clang"
WINDOWS_ARM64 = "VC-WIN64-CLANGASM-ARM"
WINDOWS_X86 = "VC-WIN64A-masm"

linux_platforms = [LINUX_ARM64, LINUX_X86]

mac_platforms = [MAC_ARM64, MAC_X86]

unix_platforms = linux_platforms + mac_platforms

windows_platforms = [WINDOWS_ARM64, WINDOWS_X86]

all_platforms = unix_platforms + windows_platforms

x86_64_platforms = [MAC_X86, LINUX_X86, WINDOWS_X86]
arm64_platforms = [MAC_ARM64, LINUX_ARM64, WINDOWS_ARM64]

# Used for generation and testing on a pull request.
WINDOWS = "windows"
UNIX = "unix"
LINUX = "linux"
MAC = "mac"
ARM64 = "arm64"
X86_64 = "x86_64"
# Used for release flow.
ALL = "all"


generated_files = [
    "apps/progs.c",
    "apps/progs.h",
    "crypto/buildinf.h",
    "crypto/params_idx.c",
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
    "providers/common/der/der_digests_gen.c",
    "providers/common/der/der_dsa_gen.c",
    "providers/common/der/der_ec_gen.c",
    "providers/common/der/der_ecx_gen.c",
    "providers/common/der/der_rsa_gen.c",
    "providers/common/der/der_sm2_gen.c",
    "providers/common/der/der_wrap_gen.c",
    "providers/common/include/prov/der_digests.h",
    "providers/common/include/prov/der_dsa.h",
    "providers/common/include/prov/der_ec.h",
    "providers/common/include/prov/der_ecx.h",
    "providers/common/include/prov/der_rsa.h",
    "providers/common/include/prov/der_sm2.h",
    "providers/common/include/prov/der_wrap.h",
]


def get_platforms(os: str):
    if os == WINDOWS:
        return windows_platforms
    elif os == UNIX:
        return unix_platforms
    elif os == ALL:
        return all_platforms
    else:
        raise ValueError(f"Unknown os: {os}")


def get_make_command(os: str):
    if os == WINDOWS:
        return "nmake"
    elif os == UNIX:
        return "make"
    elif os == ALL:
        return "make"
    else:
        raise ValueError(f"Unknown os: {os}")


def get_start_configure_list(os: str, platform: str):
    if os == WINDOWS:
        if platform in windows_platforms:
            # On Windows we don't  use any assembly because the assembler is mismatched
            # between MSVC with Bazel and MSVC with OpenSSL.
            # See https://github.com/rustls/boringssl/blob/018edfaaaeea43bf35a16e9f7ba24510c0c003bb/util/util.bzl#L149
            # for the inspiration.
            return ["perl", "Configure", "no-asm"]
        elif platform in unix_platforms:
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


def get_extra_tar_options(os: str):
    all_tar_options = ["--owner", "root", "--group", "wheel", "--mtime=UTC 1980-01-01"]
    if os == WINDOWS:
        return []
    elif os == UNIX:
        return all_tar_options
    elif os == ALL:
        return all_tar_options
    else:
        raise ValueError(f"Unknown os: {os}")


def get_simple_platform(platform: str):
    if platform in windows_platforms:
        return WINDOWS
    elif platform in unix_platforms:
        return UNIX
    else:
        raise ValueError(f"Unknown platform: {platform}")


def get_specific_common_platform(platform: str):
    if platform in windows_platforms:
        return WINDOWS
    elif platform in linux_platforms:
        return LINUX
    elif platform in mac_platforms:
        return MAC
    else:
        raise ValueError(f"Unknown platform: {platform}")


def get_architecture(platform: str):
    if platform in arm64_platforms:
        return ARM64
    elif platform in x86_64_platforms:
        return X86_64
    else:
        raise ValueError(f"Unknown platform: {platform}")


def get_tar_platform(platform: str):
    # For now we just return platform but we want this
    # in case we change how they are output
    return platform


def get_dir_to_copy(root: str, platform: str):
    return os.path.join(
        root,
        f"{get_simple_platform(platform)}_unzipped",
        get_specific_common_platform(platform),
        get_architecture(platform),
        "tmp",
    )


@contextmanager
def download_openssl(version: str, simple_platform: str):
    prefix_dir = f"openssl-{version}"
    tempdir = ""
    try:
        tempdir = "/tmp"
        if simple_platform == WINDOWS:
            tempdir = "C:/tmp"
        if not os.path.exists(tempdir):
            os.makedirs(tempdir)
        tar_path = pathlib.Path(os.path.join(tempdir, "openssl.tar.gz"))
        url = f"https://github.com/openssl/openssl/releases/download/openssl-{version}/openssl-{version}.tar.gz"
        subprocess.check_call(
            ["curl", "--fail", "-L", "-o", tar_path, url],
        )
        subprocess.check_call(["tar", "xzf", tar_path], cwd=tempdir)

        openssl_info = {
            "url": url,
            "integrity": integrity_hash(tar_path),
            "strip_prefix": prefix_dir,
        }

        yield pathlib.Path(os.path.join(tempdir, prefix_dir)), openssl_info
    # On Windows this step can fail and we need to retry. But first clean things up.
    except Exception as e:
        cleanup(prefix_dir, tempdir)
        raise e


def cleanup(prefix_dir: str, tempdir: str):
    if os.path.exists(prefix_dir):
        shutil.rmtree(prefix_dir, ignore_errors=True)
    if os.path.exists(tempdir):
        shutil.rmtree(tempdir, ignore_errors=True)


def integrity_hash(path: str) -> str:
    algo = "sha256"
    with open(pathlib.Path(path).resolve(), "rb") as f:
        digest = hashlib.file_digest(f, algo).digest()
    return f"{algo}-{base64.b64encode(digest).decode('utf-8')}"


def copy_from_here_to(local_path: str, dst: str, executable: bool = False):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(pathlib.Path(os.path.join(os.path.dirname(__file__), local_path)), dst)
    if executable:
        if platform.system == "Windows":
            os.access(dst, os.R_OK | os.W_OK | os.X_OK)
        else:
            os.chmod(dst, 0o755)
