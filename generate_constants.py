"""Generate tiered source list constants for the OpenSSL Bazel overlay.

Runs OpenSSL's Configure for each target platform on a single machine,
extracts source lists via extract_srcs.pl, and computes tiered constants:
  - common.bzl: sources shared by ALL platforms
  - no_asm.bzl: C fallback sources for unknown platforms
  - per-platform .bzl: assembly deltas for each known platform

This replaces both generate_per_platform.py and generate_combine_platforms.py.
No `make` step is needed -- Configure is pure Perl and runs for any target
on any host machine.
"""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from textwrap import dedent
from typing import Any, NamedTuple

from common import (
    ALL_PLATFORMS,
    IOS_PLATFORMS,
    MAC_PLATFORMS,
    NO_ASM_TARGET,
    OPENSSL_VERSION,
    WINDOWS_PLATFORMS,
    copy_from_here_to,
    get_configure_target,
    get_simple_config_name,
    integrity_hash,
)


class ConfigHeaderData(NamedTuple):
    """Config header template values extracted from configdata.pm."""

    b64l: bool
    b64: bool
    b32: bool
    bn_ll: bool
    rc4_int: str
    processor: str
    openssl_sys_defines: list[str]
    openssl_api_defines: list[str]
    openssl_feature_defines: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConfigHeaderData":
        def _str_list(key: str) -> list[str]:
            val = data.get(key, [])
            assert isinstance(val, list)
            return [str(x) for x in val]

        return cls(
            b64l=bool(data["config_b64l"]),
            b64=bool(data["config_b64"]),
            b32=bool(data["config_b32"]),
            bn_ll=bool(data["config_bn_ll"]),
            rc4_int=str(data.get("config_rc4_int", "unsigned int")),
            processor=str(data.get("config_processor", "")),
            openssl_sys_defines=_str_list("config_openssl_sys_defines"),
            openssl_api_defines=_str_list("config_openssl_api_defines"),
            openssl_feature_defines=_str_list("config_openssl_feature_defines"),
        )


class PlatformData(NamedTuple):
    """Source lists and build metadata extracted from configdata.pm for one platform."""

    libcrypto_srcs: list[str]
    libssl_srcs: list[str]
    openssl_app_srcs: list[str]
    perlasm_gen_commands: list[str]
    libcrypto_defines: list[str]
    libssl_defines: list[str]
    openssl_app_defines: list[str]
    openssl_defines: list[str]
    disablables: list[str]
    config_header_data: ConfigHeaderData

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlatformData":
        def _str_list(key: str) -> list[str]:
            val = data.get(key, [])
            assert isinstance(val, list)
            return [str(x) for x in val]

        str_lists: dict[str, list[str]] = {}
        for key in [
            "libcrypto_srcs",
            "libssl_srcs",
            "openssl_app_srcs",
            "perlasm_gen_commands",
            "libcrypto_defines",
            "libssl_defines",
            "openssl_app_defines",
            "openssl_defines",
            "disablables",
        ]:
            str_lists[key] = _str_list(key)
        return cls(
            libcrypto_srcs=str_lists["libcrypto_srcs"],
            libssl_srcs=str_lists["libssl_srcs"],
            openssl_app_srcs=str_lists["openssl_app_srcs"],
            perlasm_gen_commands=sorted(set(str_lists["perlasm_gen_commands"])),
            libcrypto_defines=sorted(set(str_lists["libcrypto_defines"])),
            libssl_defines=sorted(set(str_lists["libssl_defines"])),
            openssl_app_defines=sorted(set(str_lists["openssl_app_defines"])),
            openssl_defines=sorted(set(str_lists["openssl_defines"])),
            disablables=str_lists["disablables"],
            config_header_data=ConfigHeaderData.from_dict(data),
        )

    def all_crypto_srcs(self) -> set[str]:
        return set(self.libcrypto_srcs)

    def all_ssl_srcs(self) -> set[str]:
        return set(self.libssl_srcs)

    def all_app_srcs(self) -> set[str]:
        return set(self.openssl_app_srcs)


def run_configure(openssl_dir: Path, platform: str) -> None:
    """Run OpenSSL's Configure for a given target platform.

    We only need configdata.pm from this step. On non-Windows hosts,
    Configure for Windows targets may fail during Makefile generation
    (Perl can't produce Windows-style paths), but configdata.pm is
    created before that step. We tolerate the failure as long as
    configdata.pm exists.
    """
    configdata_path = openssl_dir / "configdata.pm"
    if configdata_path.exists():
        configdata_path.unlink()

    write_config_file(openssl_dir, platform)

    configure_cmd = ["perl", "Configure"]
    if platform == NO_ASM_TARGET:
        configure_cmd += [
            "--config=config.conf",
            "openssl_config",
            "no-afalgeng",
            "no-dynamic-engine",
            "no-asm",
        ]
    else:
        configure_cmd += [
            "--config=config.conf",
            "openssl_config",
            "no-afalgeng",
            "no-dynamic-engine",
        ]

    env = os.environ.copy()
    if platform in WINDOWS_PLATFORMS:
        env["CONFIGURE_INSIST"] = "1"

    result = subprocess.run(configure_cmd, cwd=openssl_dir, env=env)
    if not configdata_path.exists():
        raise RuntimeError(
            f"Configure for {platform} failed and configdata.pm was not produced. Exit code: {result.returncode}"
        )
    if result.returncode != 0:
        print(
            f"  WARNING: Configure exited {result.returncode} for {platform}, "
            f"but configdata.pm exists -- proceeding (Makefile generation "
            f"failure is expected on cross-compilation hosts)"
        )


# Android targets need NDK tools at configure time. We bypass this by
# inheriting from linux-generic32 (what "android" inherits from) directly,
# preserving only asm_arch and perlasm_scheme which determine source lists.
_ANDROID_CONFIG_OVERRIDES = {
    "android-arm64": {
        "inherit_from": "linux-aarch64",
        "asm_arch": "aarch64",
        "perlasm_scheme": "linux64",
    },
    "android-x86_64": {
        "inherit_from": "linux-x86_64",
        "asm_arch": "x86_64",
        "perlasm_scheme": "elf",
    },
}


def write_config_file(openssl_dir: Path, platform: str) -> None:
    target = get_configure_target(platform)
    override = _ANDROID_CONFIG_OVERRIDES.get(target)
    if override:
        with (openssl_dir / "config.conf").open("w") as f:
            f.write(
                f"""(
    'openssl_config' => {{
        inherit_from   => [ "{override["inherit_from"]}" ],
        asm_arch       => '{override["asm_arch"]}',
        perlasm_scheme => '{override["perlasm_scheme"]}',
        dso_scheme     => undef,
    }}
);
"""
            )
    else:
        with (openssl_dir / "config.conf").open("w") as f:
            f.write(
                f"""(
    'openssl_config' => {{
        inherit_from => [ "{target}" ],
        dso_scheme   => undef,
    }}
);
"""
            )


def extract_platform_data(openssl_dir: Path, platform: str) -> PlatformData:
    """Run Configure and extract source lists for a platform."""
    run_configure(openssl_dir, platform)

    simple_platform = "windows" if "WIN" in get_configure_target(platform) else "unix"
    proc = subprocess.run(
        [
            "perl",
            "-I.",
            "-l",
            "-Mconfigdata",
            str(Path(__file__).parent / "extract_srcs.pl"),
            simple_platform,
        ],
        cwd=openssl_dir,
        stdout=subprocess.PIPE,
        check=True,
    )
    data = json.loads(proc.stdout.decode("utf-8"))
    return PlatformData.from_dict(data)


def compute_tiered_constants(
    platform_data: dict[str, PlatformData],
    no_asm_data: PlatformData,
) -> dict[str, Any]:
    """Compute tiered source lists from per-platform data.

    Returns a dict with:
      - common_crypto_srcs: intersection of all platform crypto srcs
      - common_ssl_srcs: intersection of all platform ssl srcs (usually identical)
      - common_app_srcs: intersection of all platform app srcs
      - no_asm_crypto_extra: sources in no-asm but not in common
      - per_platform: dict of platform -> delta data
    """
    all_crypto = [d.all_crypto_srcs() for d in platform_data.values()]
    all_ssl = [d.all_ssl_srcs() for d in platform_data.values()]
    all_app = [d.all_app_srcs() for d in platform_data.values()]

    common_crypto = set.intersection(*all_crypto, no_asm_data.all_crypto_srcs())
    common_ssl = set.intersection(*all_ssl, no_asm_data.all_ssl_srcs())
    common_app = set.intersection(*all_app, no_asm_data.all_app_srcs())

    no_asm_crypto_extra = no_asm_data.all_crypto_srcs() - common_crypto
    no_asm_ssl_extra = no_asm_data.all_ssl_srcs() - common_ssl
    no_asm_app_extra = no_asm_data.all_app_srcs() - common_app

    per_platform = {}
    for name, data in platform_data.items():
        per_platform[name] = {
            "asm_crypto_extra": sorted(data.all_crypto_srcs() - common_crypto),
            "asm_ssl_extra": sorted(data.all_ssl_srcs() - common_ssl),
            "asm_app_extra": sorted(data.all_app_srcs() - common_app),
            "perlasm_gen": data.perlasm_gen_commands,
            "libcrypto_defines": data.libcrypto_defines,
            "libssl_defines": data.libssl_defines,
            "openssl_app_defines": data.openssl_app_defines,
            "openssl_defines": data.openssl_defines,
        }

    return {
        "common_crypto_srcs": sorted(common_crypto),
        "common_ssl_srcs": sorted(common_ssl),
        "common_app_srcs": sorted(common_app),
        "no_asm_crypto_extra": sorted(no_asm_crypto_extra),
        "no_asm_ssl_extra": sorted(no_asm_ssl_extra),
        "no_asm_app_extra": sorted(no_asm_app_extra),
        "no_asm_defines": no_asm_data.openssl_defines,
        "per_platform": per_platform,
    }


def write_common_bzl(output_dir: Path, tiered: dict[str, Any]) -> None:
    indent = " " * 4
    content = f"""\
# Generated code. DO NOT EDIT.

COMMON_CRYPTO_SRCS = {json.dumps(tiered["common_crypto_srcs"], indent=indent)}

COMMON_SSL_SRCS = {json.dumps(tiered["common_ssl_srcs"], indent=indent)}

COMMON_APP_SRCS = {json.dumps(tiered["common_app_srcs"], indent=indent)}
"""
    (output_dir / "common.bzl").write_text(content)


def write_no_asm_bzl(output_dir: Path, tiered: dict[str, Any]) -> None:
    indent = " " * 4
    content = f"""\
# Generated code. DO NOT EDIT.

NO_ASM_CRYPTO_EXTRA_SRCS = {json.dumps(tiered["no_asm_crypto_extra"], indent=indent)}

NO_ASM_SSL_EXTRA_SRCS = {json.dumps(tiered["no_asm_ssl_extra"], indent=indent)}

NO_ASM_APP_EXTRA_SRCS = {json.dumps(tiered["no_asm_app_extra"], indent=indent)}

NO_ASM_DEFINES = {json.dumps(tiered["no_asm_defines"], indent=indent)}
"""
    (output_dir / "no_asm.bzl").write_text(content)


def write_platform_bzl(output_dir: Path, config_name: str, platform_delta: dict[str, Any]) -> None:
    indent = " " * 4
    content = f"""\
# Generated code. DO NOT EDIT.

ASM_CRYPTO_EXTRA_SRCS = {json.dumps(platform_delta["asm_crypto_extra"], indent=indent)}

ASM_SSL_EXTRA_SRCS = {json.dumps(platform_delta["asm_ssl_extra"], indent=indent)}

ASM_APP_EXTRA_SRCS = {json.dumps(platform_delta["asm_app_extra"], indent=indent)}

PERLASM_GEN = "\\n".join({json.dumps(platform_delta["perlasm_gen"], indent=indent)})

LIBCRYPTO_DEFINES = {json.dumps(platform_delta["libcrypto_defines"], indent=indent)}

LIBSSL_DEFINES = {json.dumps(platform_delta["libssl_defines"], indent=indent)}

OPENSSL_APP_DEFINES = {json.dumps(platform_delta["openssl_app_defines"], indent=indent)}

OPENSSL_DEFINES = {json.dumps(platform_delta["openssl_defines"], indent=indent)}
"""
    (output_dir / f"{config_name}.bzl").write_text(content)


def _get_platform_metadata(platform: str) -> tuple[str, str, str]:
    """Return (perl_platform, dso_scheme, dso_extension) for a platform.

    These values are deterministic from the platform type and don't need
    extraction from configdata.pm (where dso_scheme is overridden to undef).
    """
    if platform in WINDOWS_PLATFORMS:
        return ("Windows", "WIN32", ".dll")
    if platform in MAC_PLATFORMS or platform in IOS_PLATFORMS:
        return ("Unix", "DLFCN", ".dylib")
    return ("Unix", "DLFCN", ".so")


class _ConfigProfile(NamedTuple):
    """Distinct config header output profile (for deduplication)."""

    b64l: bool
    b64: bool
    b32: bool
    bn_ll: bool
    rc4_int: str
    processor: str
    openssl_sys_defines: tuple[str, ...]
    openssl_api_defines: tuple[str, ...]
    openssl_feature_defines: tuple[str, ...]
    perl_platform: str
    dso_scheme: str
    dso_extension: str
    disablables: tuple[str, ...]


def _make_profile(
    hdr: ConfigHeaderData,
    platform: str,
    disablables: list[str],
) -> _ConfigProfile:
    perl_platform, dso_scheme, dso_extension = _get_platform_metadata(platform)
    return _ConfigProfile(
        b64l=hdr.b64l,
        b64=hdr.b64,
        b32=hdr.b32,
        bn_ll=hdr.bn_ll,
        rc4_int=hdr.rc4_int,
        processor=hdr.processor,
        openssl_sys_defines=tuple(hdr.openssl_sys_defines),
        openssl_api_defines=tuple(hdr.openssl_api_defines),
        openssl_feature_defines=tuple(hdr.openssl_feature_defines),
        perl_platform=perl_platform,
        dso_scheme=dso_scheme,
        dso_extension=dso_extension,
        disablables=tuple(disablables),
    )


def _render_perl_list(items: tuple[str, ...] | list[str]) -> str:
    """Render a Python list as a Perl array literal."""
    if not items:
        return "[]"
    inner = ", ".join(f'"{item}"' for item in items)
    return f"[{inner}]"


_CONFIGDATA_TEMPLATE = (Path(__file__).parent / "configdata.pm.in").read_text()


def _render_configdata_stub(profile: _ConfigProfile) -> str:
    """Render a complete configdata.pm stub for a given config profile."""
    feature_lines = [f'        "{d}",' for d in profile.openssl_feature_defines]
    feature_block = "[\n" + "\n".join(feature_lines) + "\n    ]" if feature_lines else "[]"

    disablables_str = " ".join(profile.disablables)

    replacements = {
        "@@B64L@@": str(1 if profile.b64l else 0),
        "@@B64@@": str(1 if profile.b64 else 0),
        "@@B32@@": str(1 if profile.b32 else 0),
        "@@BN_LL@@": str(1 if profile.bn_ll else 0),
        "@@RC4_INT@@": profile.rc4_int,
        "@@PROCESSOR@@": profile.processor,
        "@@SYS_DEFINES@@": _render_perl_list(profile.openssl_sys_defines),
        "@@API_DEFINES@@": _render_perl_list(profile.openssl_api_defines),
        "@@FEATURE_DEFINES@@": feature_block,
        "@@PERL_PLATFORM@@": profile.perl_platform,
        "@@DSO_SCHEME@@": profile.dso_scheme,
        "@@DSO_EXTENSION@@": profile.dso_extension,
        "@@DISABLABLES@@": disablables_str,
    }

    result = _CONFIGDATA_TEMPLATE
    for marker, value in replacements.items():
        result = result.replace(marker, value)
    return result


def generate_configdata_stubs(
    platform_data: dict[str, PlatformData],
    no_asm_data: PlatformData,
    output_dir: Path,
) -> None:
    """Generate per-platform configdata stubs.

    Writes one configdata.pm per config_name into
    output_dir/configdata/<config_name>/configdata.pm, so that perl_library
    can set includes to find it as 'configdata'.
    """
    configdata_base = output_dir / "configdata"
    configdata_base.mkdir(parents=True, exist_ok=True)

    # @disablables is identical across all platforms; take from any.
    disablables = next(iter(platform_data.values())).disablables

    for platform, data in platform_data.items():
        config_name = get_simple_config_name(platform)
        profile = _make_profile(data.config_header_data, platform, disablables)
        subdir = configdata_base / config_name
        subdir.mkdir(parents=True, exist_ok=True)
        (subdir / "configdata.pm").write_text(_render_configdata_stub(profile))

    no_asm_profile = _make_profile(no_asm_data.config_header_data, NO_ASM_TARGET, disablables)
    no_asm_subdir = configdata_base / "no_asm"
    no_asm_subdir.mkdir(parents=True, exist_ok=True)
    (no_asm_subdir / "configdata.pm").write_text(_render_configdata_stub(no_asm_profile))


def write_constants_build(output_dir: Path) -> None:
    (output_dir / "BUILD.bazel").write_text("")


def write_bazel_build(bazel_dir: Path) -> None:
    """Write the BUILD.bazel for the bazel/ overlay package."""
    content = """\
load("@rules_cc//cc:cc_binary.bzl", "cc_binary")
load("@rules_perl//perl:perl.bzl", "perl_binary")

cc_binary(
    name = "redirect_stdout",
    srcs = ["redirect_stdout.cc"],
    visibility = ["//:__pkg__"],
)

perl_binary(
    name = "batch_dofile",
    srcs = ["batch_dofile.pl"],
    main = "batch_dofile.pl",
    perlopt = [
        "-Mconfigdata",
        "-Moids_to_c",
    ],
    visibility = ["//:__pkg__"],
    deps = [
        "//:configdata",
        "//:der_codegen",
        "//:external_perl",
        "//:openssl_platform",
        "//:perl_utils",
    ],
)
"""
    (bazel_dir / "BUILD.bazel").write_text(content)


# Features that should NOT be exposed as user-facing bool_flags.
# Everything in @disablables not in this set gets a flag.
_SKIP_DISABLABLES = frozenset(
    {
        # No OPENSSL_NO_* define emitted by Configure
        "buildtest-c++",
        "fips",
        "threads",
        "shared",
        "module",
        "pic",
        "dynamic-engine",
        "makedepend",
        "sse2",
        "legacy",
        # Already disabled in the overlay's Configure invocation
        "afalgeng",
        # Build-model decisions not configurable in Bazel
        "asm",
        "static-engine",
        "apps",
        "pinshared",
        # Testing / debugging only
        "acvp-tests",
        "asan",
        "msan",
        "ubsan",
        "crypto-mdebug",
        "external-tests",
        "unit-test",
        "fuzz-afl",
        "fuzz-libfuzzer",
        "tests",
        "demos",
        # Internal implementation details
        "autoalginit",
        "autoerrinit",
        "autoload-config",
        "bulk",
        "cached-fetch",
        "default-thread-pool",
        "thread-pool",
        "err",
        "filenames",
        "integrity-only-ciphers",
        "multiblock",
        "posix-io",
        "rdrand",
        "secure-memory",
        "stdio",
        "trace",
        "weak-ssl-ciphers",
        "uplink",
        # Require external libraries
        "brotli",
        "zlib",
        "zlib-dynamic",
        "zstd",
        # Platform-specific engine modules
        "capieng",
        "devcryptoeng",
        "loadereng",
        "padlockeng",
        # Too broad / structural
        "tls",
        "ssl",
        "dso",
        "dgram",
        # Internal FIPS details
        "fips-post",
        "fips-securitychecks",
    }
)


def _feature_to_define(feature: str) -> str:
    """Map a disablable feature name to its OPENSSL_NO_* define."""
    return "-DOPENSSL_NO_" + feature.upper().replace("-", "_")


def _feature_to_setting_name(feature: str) -> str:
    """Map a disablable feature name to a config_setting name."""
    return feature.replace("-", "_") + "_disabled"


def get_user_features(disablables: list[str]) -> list[str]:
    """Filter disablables to user-relevant features, sorted."""
    return sorted(f for f in disablables if f not in _SKIP_DISABLABLES)


def write_features_bzl(constants_dir: Path, features: list[str]) -> None:
    """Generate features.bzl with FEATURE_DEFINES, flag macro, and config_setting macro."""
    if not features:
        (constants_dir / "features.bzl").write_text(
            "# Generated code. DO NOT EDIT.\n\n"
            'load("@bazel_skylib//rules:common_settings.bzl", "bool_flag")\n\n'
            "FEATURE_DEFINES = []\n\n"
            "def openssl_feature_flags():\n    pass\n\n"
            "def openssl_feature_config_settings():\n    pass\n"
        )
        return

    lines = [
        "# Generated code. DO NOT EDIT.\n\n",
        'load("@bazel_skylib//rules:common_settings.bzl", "bool_flag")\n\n',
    ]

    # FEATURE_DEFINES
    blocks = []
    for feature in features:
        setting = _feature_to_setting_name(feature)
        define = _feature_to_define(feature)
        blocks.append(f'select({{\n    "//configs:{setting}": ["{define}"],\n    "//conditions:default": [],\n}})')
    joined = " + \\\n    ".join(blocks)
    lines.append(f"FEATURE_DEFINES = {joined}\n\n")

    # openssl_feature_flags macro (creates bool_flag targets in root BUILD)
    lines.append("def openssl_feature_flags():\n")
    for feature in features:
        lines.append(
            f'    bool_flag(name = "no-{feature}", build_setting_default = False, visibility = ["//visibility:public"])\n'
        )
    lines.append("\n")

    # openssl_feature_config_settings macro (creates config_settings in configs/)
    lines.append("def openssl_feature_config_settings():\n")
    for feature in features:
        setting = _feature_to_setting_name(feature)
        lines.append(
            f"    native.config_setting(\n"
            f'        name = "{setting}",\n'
            f'        flag_values = {{"//:no-{feature}": "True"}},\n'
            f'        visibility = ["//:__subpackages__"],\n'
            f"    )\n"
        )

    (constants_dir / "features.bzl").write_text("".join(lines))


def main(
    openssl_source_dir: str,
    output_dir: str,
    bcr_dir: str | None,
    tag: str | None,
    buildifier_path: str,
    source_archive: str | None = None,
) -> None:
    openssl_dir = Path(openssl_source_dir)
    out = Path(output_dir)

    constants_dir = out / "bazel" / "constants"
    constants_dir.mkdir(parents=True, exist_ok=True)

    platform_data: dict[str, PlatformData] = {}

    print("=== Extracting source lists for all platforms ===")
    for platform in ALL_PLATFORMS:
        config_name = get_simple_config_name(platform)
        print(f"  Configuring for {platform} ({config_name})...")
        data = extract_platform_data(openssl_dir, platform)
        platform_data[platform] = data

    print("  Configuring for no-asm fallback...")
    no_asm_data = extract_platform_data(openssl_dir, NO_ASM_TARGET)

    print("=== Computing tiered constants ===")
    tiered = compute_tiered_constants(platform_data, no_asm_data)

    print("=== Writing .bzl files ===")
    write_common_bzl(constants_dir, tiered)
    write_no_asm_bzl(constants_dir, tiered)
    write_constants_build(constants_dir)

    for platform in ALL_PLATFORMS:
        config_name = get_simple_config_name(platform)
        write_platform_bzl(constants_dir, config_name, tiered["per_platform"][platform])

    # @disablables is identical across all platforms; take from any.
    disablables = next(iter(platform_data.values())).disablables
    user_features = get_user_features(disablables)

    print("=== Generating feature toggle flags ===")
    write_features_bzl(constants_dir, user_features)

    print("=== Generating per-platform configdata stubs ===")
    generate_configdata_stubs(platform_data, no_asm_data, out)

    # Overlay root = out. All overlay files go under out for correct load paths.
    overlay_dir = out
    copy_from_here_to("BUILD.openssl.bazel", overlay_dir / "BUILD.bazel")
    (overlay_dir / "configs").mkdir(parents=True, exist_ok=True)
    copy_from_here_to("BUILD.configs.bazel", overlay_dir / "configs" / "BUILD.bazel")
    copy_from_here_to("perl_genrule.bzl", overlay_dir / "bazel" / "perl_genrule.bzl")
    copy_from_here_to("openssl_genrule.bzl", overlay_dir / "bazel" / "openssl_genrule.bzl")
    copy_from_here_to("redirect_stdout.cc", overlay_dir / "bazel" / "redirect_stdout.cc")
    copy_from_here_to("batch_dofile.pl", overlay_dir / "bazel" / "batch_dofile.pl")
    write_bazel_build(overlay_dir / "bazel")
    copy_from_here_to("utils.bzl", overlay_dir / "utils.bzl")
    copy_from_here_to("presubmit.yml", overlay_dir / "presubmit.yml")

    (overlay_dir / "test_bazel_build").mkdir(parents=True, exist_ok=True)
    copy_from_here_to("BUILD.test.bazel", overlay_dir / "test_bazel_build" / "BUILD.bazel")
    copy_from_here_to("sha256_test.cc", overlay_dir / "test_bazel_build" / "sha256_test.cc")
    copy_from_here_to("build_test.cc", overlay_dir / "test_bazel_build" / "build_test.cc")

    if buildifier_path:
        print("=== Formatting with buildifier ===")
        subprocess.run(
            [buildifier_path, "-lint=fix", "-mode=fix", "-r", str(out)],
            check=True,
        )

    if bcr_dir and tag:
        if not source_archive:
            raise RuntimeError(
                "--source_archive is required when generating BCR files (--bcr_dir and --tag were provided)"
            )
        write_bcr_files(out, bcr_dir, tag, source_archive)

    print("=== Done ===")
    print(f"Overlay written to: {out}")


def write_bcr_files(out: Path, bcr_dir: str, tag: str, source_archive: str) -> None:
    """Write BCR module files. Overlay root is out (contains BUILD.bazel, bazel/, configs/, etc.)."""
    openssl_module_dir = Path(bcr_dir) / "modules" / "openssl"
    out_dir = openssl_module_dir / tag

    copy_from_here_to("presubmit.yml", out_dir / "presubmit.yml")

    module_bazel_content = dedent(f"""\
        module(
            name = "openssl",
            version = "{tag}",
            bazel_compatibility = [">=7.2.1"],
            compatibility_level = 3030100,
        )

        bazel_dep(name = "bazel_skylib", version = "1.7.1")
        bazel_dep(name = "platforms", version = "1.0.0")
        bazel_dep(name = "rules_cc", version = "0.2.4")
        bazel_dep(name = "rules_perl", version = "1.0.0")
    """)

    module_path = out_dir / "MODULE.bazel"
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(module_bazel_content)

    overlay_module = out / "MODULE.bazel"
    if overlay_module.exists():
        overlay_module.unlink()
    shutil.copy2(module_path, overlay_module)

    overlay_info: dict[str, str] = {}
    overlay_dst = out_dir / "overlay"
    for root, _, files in os.walk(out):
        for file in files:
            full_path = Path(root) / file
            rel = os.path.relpath(full_path, out)
            overlay_info[rel] = integrity_hash(full_path)
            dst = overlay_dst / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(full_path, dst)

    source_json = {
        "integrity": integrity_hash(Path(source_archive)),
        "url": f"https://github.com/openssl/openssl/releases/download/openssl-{OPENSSL_VERSION}/openssl-{OPENSSL_VERSION}.tar.gz",
        "strip_prefix": f"openssl-{OPENSSL_VERSION}",
        "overlay": overlay_info,
    }
    (out_dir / "source.json").write_text(json.dumps(source_json, indent="    ", sort_keys=True) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate tiered OpenSSL Bazel constants")
    parser.add_argument("--openssl_source_dir", required=True, help="Path to OpenSSL source tree")
    parser.add_argument("--output_dir", required=True, help="Output directory for generated files")
    parser.add_argument("--bcr_dir", required=False, help="BCR directory for module registration")
    parser.add_argument("--tag", required=False, help="Version tag for BCR")
    parser.add_argument("--buildifier", default="", help="Path to buildifier for formatting")
    parser.add_argument("--source_archive", required=False, help="Path to source tarball for BCR integrity hash")
    args = parser.parse_args()
    main(args.openssl_source_dir, args.output_dir, args.bcr_dir, args.tag, args.buildifier, args.source_archive)
