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
import time
from pathlib import Path
from textwrap import dedent
from typing import Any, NamedTuple

from common import (
    ALL_PLATFORMS,
    IOS_PLATFORMS,
    MAC_PLATFORMS,
    NO_ASM_TARGET,
    OPENSSL_VERSION,
    PLATFORM_CONSTRAINTS,
    WINDOWS_PLATFORMS,
    copy_from_here_to,
    get_configure_target,
    get_simple_config_name,
    integrity_hash,
    script_dir,
)


def _resolve_from_rlocation(env_var: str) -> str | None:
    """Resolve an executable from a ``*_RLOCATIONPATH`` env var via runfiles."""
    rlocation = os.environ.get(env_var)
    if rlocation:
        runfiles_dir = os.environ.get("RUNFILES_DIR", "")
        if runfiles_dir:
            candidate = os.path.join(runfiles_dir, rlocation)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None


def _resolve_perl(perl_flag: str | None) -> str:
    """Determine the Perl interpreter path.

    Precedence:
      1. Explicit ``--perl`` flag
      2. ``PERL_RLOCATIONPATH`` env var (set by the Bazel py_binary ``env``
         attribute from the rules_perl toolchain) resolved via ``RUNFILES_DIR``
      3. System ``perl`` from PATH
    """
    if perl_flag:
        return perl_flag
    return _resolve_from_rlocation("PERL_RLOCATIONPATH") or shutil.which("perl") or "perl"


def _resolve_buildifier(buildifier_flag: str | None) -> str:
    """Determine the buildifier path.

    Precedence:
      1. Explicit ``--buildifier`` flag (empty string means skip formatting)
      2. ``BUILDIFIER_RLOCATIONPATH`` env var resolved via ``RUNFILES_DIR``
      3. System ``buildifier`` from PATH
      4. Empty string (skip formatting)
    """
    if buildifier_flag is not None:
        return buildifier_flag
    return _resolve_from_rlocation("BUILDIFIER_RLOCATIONPATH") or shutil.which("buildifier") or ""


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


def run_configure(openssl_dir: Path, platform: str, perl_path: str = "perl") -> None:
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

    configure_cmd = [perl_path, "Configure"]
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


def extract_platform_data(
    openssl_dir: Path,
    platform: str,
    perl_path: str = "perl",
) -> PlatformData:
    """Run Configure and extract source lists for a platform."""
    run_configure(openssl_dir, platform, perl_path=perl_path)

    simple_platform = "windows" if "WIN" in get_configure_target(platform) else "unix"
    proc = subprocess.run(
        [
            perl_path,
            "-I.",
            "-l",
            "-Mconfigdata",
            str(script_dir() / "extract_srcs.pl"),
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


def _configdata_template() -> str:
    return (script_dir() / "configdata.pm.in").read_text()


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

    result = _configdata_template()
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


# ---------------------------------------------------------------------------
# Pre-generation: template processing, progs, buildinf, perlasm
# ---------------------------------------------------------------------------


def discover_dofile_templates(openssl_dir: Path) -> dict[str, str]:
    """Map each util/dofile.pl input path (relative to the OpenSSL root) to its output path.

    Scans the same subtrees OpenSSL uses for generated headers and sources, so new
    ``*.in`` templates are picked up when upgrading the upstream tarball without
    editing this script.
    """
    roots = [
        openssl_dir / "include",
        openssl_dir / "crypto",
        openssl_dir / "providers" / "common" / "include" / "prov",
        openssl_dir / "providers" / "common" / "der",
    ]
    found: dict[str, str] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.in"):
            rel_in = path.relative_to(openssl_dir).as_posix()
            out = (path.parent / path.stem).relative_to(openssl_dir).as_posix()
            found[rel_in] = out
    if not found:
        raise RuntimeError(
            f"No *.in dofile templates found under {openssl_dir} (expected include/, crypto/, providers/common/...)"
        )
    return dict(sorted(found.items()))


# Templates whose output varies by platform (uses %config or %target values
# that differ across configdata stubs).
_PLATFORM_SPECIFIC_TEMPLATE_INPUTS: frozenset[str] = frozenset(
    {
        "include/openssl/configuration.h.in",
        "include/crypto/bn_conf.h.in",
        "include/crypto/dso_conf.h.in",
    }
)

_HERMETIC_DOFILE_ENV = {
    "SOURCE_DATE_EPOCH": "443779200",
}

# Perlasm flavor → source platform (whose perlasm_gen_commands define the
# script set) and the config_names that consume this flavor.
_PERLASM_FLAVORS: dict[str, dict[str, Any]] = {
    "elf": {
        "source_platform": "linux-x86_64-clang",
        "consumers": ["linux_x86_64", "android_x86_64", "freebsd_x86_64"],
    },
    "macosx": {
        "source_platform": "linux-x86_64-clang",
        "consumers": ["darwin_x86_64"],
    },
    "masm": {
        "source_platform": "VC-WIN64A-masm",
        "consumers": ["windows_x64"],
    },
    "ios64": {
        "source_platform": "darwin64-arm64-cc",
        "consumers": ["darwin_arm64", "ios_arm64"],
    },
    "linux64": {
        "source_platform": "darwin64-arm64-cc",
        "consumers": ["linux_aarch64", "android_arm64", "freebsd_aarch64"],
    },
    "win64": {
        "source_platform": "VC-WIN64-CLANGASM-ARM",
        "consumers": ["windows_arm64"],
    },
}

# Windows assembly is generated at build time via perl_genrule (not
# pre-generated) to ensure correct assembler probing.
_WINDOWS_PERLASM_FLAVORS = frozenset({"masm", "win64"})


def _place_configdata_in_source(
    openssl_dir: Path,
    overlay_configdata_dir: Path,
    config_name: str,
) -> Path:
    """Copy a configdata stub into the OpenSSL source tree at the correct depth.

    The configdata stubs use dirname(dirname(dirname(__FILE__))) to resolve
    the repo root. At build time the overlay IS the repo root so this works.
    At generator time we need $_repo_root to resolve to the OpenSSL source
    tree, so we place the stub at <openssl_dir>/configdata/<config>/configdata.pm
    (same relative depth) and return the directory.
    """
    local_dir = openssl_dir / "configdata" / config_name
    local_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        overlay_configdata_dir / "configdata.pm",
        local_dir / "configdata.pm",
    )
    return local_dir


def _cleanup_source_configdata(openssl_dir: Path) -> None:
    """Remove temporary configdata stubs from the OpenSSL source tree."""
    configdata_dir = openssl_dir / "configdata"
    if configdata_dir.exists():
        shutil.rmtree(configdata_dir)


def _run_dofile(
    openssl_dir: Path,
    configdata_dir: Path,
    template_in: str,
    output_path: Path,
    perl_path: str = "perl",
) -> None:
    """Run util/dofile.pl for a single template, capturing stdout."""
    cmd = [
        perl_path,
        f"-I{configdata_dir}",
        "-Mconfigdata",
    ]
    if template_in.startswith("providers/common/"):
        cmd += [
            f"-I{openssl_dir / 'util/perl'}",
            f"-I{openssl_dir / 'providers/common/der'}",
            "-Moids_to_c",
        ]
    cmd += [str(openssl_dir / "util" / "dofile.pl"), template_in]

    env = os.environ.copy()
    env.update(_HERMETIC_DOFILE_ENV)
    result = subprocess.run(
        cmd,
        cwd=openssl_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"dofile.pl failed for {template_in}:\n{result.stderr.decode()}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(result.stdout)


def pregenerate_templates(
    openssl_dir: Path,
    platform_data: dict[str, PlatformData],
    output_dir: Path,
    perl_path: str = "perl",
) -> None:
    """Pre-generate all dofile template outputs.

    Invariant templates are generated once (using any platform's configdata
    stub). Platform-specific templates are generated per known platform.

    The configdata stubs are temporarily placed inside the OpenSSL source tree
    so that $_repo_root (dirname^3 of __FILE__) resolves to the source root
    rather than the overlay output directory.
    """
    generated_dir = output_dir / "generated"
    all_dofile_templates = discover_dofile_templates(openssl_dir)

    try:
        # Place any platform's configdata in the source tree for invariant templates.
        any_platform = next(iter(platform_data))
        any_config = get_simple_config_name(any_platform)
        local_configdata = _place_configdata_in_source(
            openssl_dir,
            output_dir / "configdata" / any_config,
            any_config,
        )

        common_dir = generated_dir / "common"
        for template_in, template_out in all_dofile_templates.items():
            if template_in in _PLATFORM_SPECIFIC_TEMPLATE_INPUTS:
                continue
            out_path = common_dir / template_out
            print(f"    {template_out}")
            _run_dofile(openssl_dir, local_configdata, template_in, out_path, perl_path=perl_path)

        # Platform-specific templates: generate per known platform.
        for platform in platform_data:
            config_name = get_simple_config_name(platform)
            local_configdata = _place_configdata_in_source(
                openssl_dir,
                output_dir / "configdata" / config_name,
                config_name,
            )
            platform_dir = generated_dir / config_name
            for template_in, template_out in all_dofile_templates.items():
                if template_in not in _PLATFORM_SPECIFIC_TEMPLATE_INPUTS:
                    continue
                out_path = platform_dir / template_out
                print(f"    {config_name}/{template_out}")
                _run_dofile(openssl_dir, local_configdata, template_in, out_path, perl_path=perl_path)

        # Also generate for no_asm (it gets its own configdata stub).
        local_configdata = _place_configdata_in_source(
            openssl_dir,
            output_dir / "configdata" / "no_asm",
            "no_asm",
        )
        no_asm_dir = generated_dir / "no_asm"
        for template_in, template_out in all_dofile_templates.items():
            if template_in not in _PLATFORM_SPECIFIC_TEMPLATE_INPUTS:
                continue
            out_path = no_asm_dir / template_out
            print(f"    no_asm/{template_out}")
            _run_dofile(openssl_dir, local_configdata, template_in, out_path, perl_path=perl_path)

    finally:
        _cleanup_source_configdata(openssl_dir)


def pregenerate_progs(
    openssl_dir: Path,
    output_dir: Path,
    configdata_dir: Path,
    perl_path: str = "perl",
) -> None:
    """Pre-generate apps/progs.h and apps/progs.c via progs.pl.

    The configdata_dir must be inside the OpenSSL source tree so that
    $_repo_root resolves correctly (see _place_configdata_in_source).
    """
    generated_dir = output_dir / "generated" / "common" / "apps"
    generated_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update(_HERMETIC_DOFILE_ENV)

    for flag, filename in [("-H", "progs.h"), ("-C", "progs.c")]:
        result = subprocess.run(
            [
                perl_path,
                f"-I{configdata_dir}",
                "-Mconfigdata",
                str(openssl_dir / "apps" / "progs.pl"),
                flag,
                "apps/openssl",
            ],
            cwd=openssl_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"progs.pl {flag} failed:\n{result.stderr.decode()}")
        (generated_dir / filename).write_bytes(result.stdout)
        print(f"    apps/{filename}")


def _buildinf_template() -> str:
    return (script_dir() / "buildinf.h.in").read_text()


# Fixed epoch matching _HERMETIC_DOFILE_ENV for reproducible builds.
_BUILDINF_EPOCH = 443779200


def _render_compiler_flags_array(compiler_info: str) -> str:
    """Render the compiler_flags char array body matching mkbuildinf.pl output."""
    chars = []
    for i, c in enumerate(compiler_info):
        if c in ("\\", "'"):
            c = "\\" + c
        if i % 16 == 0:
            if i > 0:
                chars.append("\n")
            chars.append("    ")
        chars.append(f"'{c}',")
    chars.append("'\\0'\n")
    return "".join(chars)


def generate_buildinf_h(output_dir: Path) -> None:
    """Generate crypto/buildinf.h from the buildinf.h.in template."""
    crypto_dir = output_dir / "generated" / "common" / "crypto"
    crypto_dir.mkdir(parents=True, exist_ok=True)

    date = time.strftime("%a %b %d %H:%M:%S %Y", time.gmtime(_BUILDINF_EPOCH)) + " UTC"

    content = _buildinf_template()
    content = content.replace("@@PLATFORM@@", "bazel")
    content = content.replace("@@DATE@@", date)
    content = content.replace("@@COMPILER_FLAGS_ARRAY@@", _render_compiler_flags_array("compiler: bazel"))

    (crypto_dir / "buildinf.h").write_text(content)


def _parse_perlasm_commands(commands: list[str]) -> list[tuple[str, str]]:
    """Parse perlasm_gen_commands into (tool_path, output_path) pairs.

    Each command has the format (6 space-separated tokens):
      $(PERL) $(execpath <tool>) <scheme> $(execpath <output>);
    """
    pairs = []
    for cmd in commands:
        parts = cmd.split(" ")
        if len(parts) != 6:
            continue
        tool = parts[2].rstrip(");")
        output = parts[5].rstrip(");")
        pairs.append((tool, output))
    return pairs


def _fix_masm_segment(path: Path) -> None:
    """Ensure MASM output has a segment before any PROC directive.

    Some perlasm scripts (e.g. aes-gcm-avx512.pl, rsaz-2k-avx512.pl) emit
    functions before the first .text directive.  In GAS this is fine
    (implicit .text), but MASM requires all code inside an explicit segment
    block.  This is an upstream structural bug and applies regardless of the
    host that ran the perlasm scripts.
    """
    lines = path.read_text().splitlines(keepends=True)
    has_segment = False
    insert_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if "SEGMENT" in stripped:
            has_segment = True
            break
        if stripped.endswith("PROC PUBLIC") or stripped.endswith("PROC PRIVATE"):
            insert_idx = i
            break
    if insert_idx is not None and not has_segment:
        lines.insert(insert_idx, ".text$\tSEGMENT ALIGN(256) 'CODE'\n")
        path.write_text("".join(lines))


def pregenerate_perlasm(
    openssl_dir: Path,
    platform_data: dict[str, PlatformData],
    output_dir: Path,
    perl_path: str = "perl",
    flavors: list[str] | None = None,
) -> None:
    """Pre-generate perlasm assembly for flavor groups.

    When *flavors* is ``None`` all known flavors are generated; otherwise
    only the listed subset is processed.
    """
    generated_asm = output_dir / "generated" / "asm"

    # Build a lookup from Configure target → PlatformData.
    lookup = {p: d for p, d in platform_data.items()}

    env = os.environ.copy()
    env.setdefault("CC", "cc")

    if flavors is None:
        selected = ((f, info) for f, info in _PERLASM_FLAVORS.items() if f not in _WINDOWS_PERLASM_FLAVORS)
    else:
        selected = ((f, _PERLASM_FLAVORS[f]) for f in flavors if f in _PERLASM_FLAVORS)
    for flavor, info in selected:
        source_platform = info["source_platform"]
        data = lookup.get(source_platform)
        if data is None or not data.perlasm_gen_commands:
            print(f"    Skipping {flavor}: no perlasm commands")
            continue

        pairs = _parse_perlasm_commands(data.perlasm_gen_commands)
        flavor_dir = generated_asm / flavor
        print(f"    {flavor}: {len(pairs)} scripts")

        for tool_path, output_path in pairs:
            out_file = flavor_dir / output_path
            out_file.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    perl_path,
                    str(openssl_dir / tool_path),
                    flavor,
                    str(out_file),
                ],
                cwd=openssl_dir,
                env=env,
                check=True,
            )
            if flavor == "masm":
                _fix_masm_segment(out_file)


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


def write_features_bzl(
    constants_dir: Path,
    features: list[str],
    known_platforms: list[str] | None = None,
) -> None:
    """Generate features.bzl with FEATURE_DEFINES, flag macro, config_setting macro,
    and pregen config_setting_group macro."""
    loads = (
        "# Generated code. DO NOT EDIT.\n\n"
        'load("@bazel_skylib//lib:selects.bzl", "selects")\n'
        'load("@bazel_skylib//rules:common_settings.bzl", "bool_flag")\n\n'
    )

    if not features:
        (constants_dir / "features.bzl").write_text(
            loads
            + "FEATURE_DEFINES = []\n\n"
            + "def openssl_feature_flags():\n    pass\n\n"
            + "def openssl_feature_config_settings():\n    pass\n\n"
            + _render_pregen_config_settings_macro(known_platforms or [])
        )
        return

    lines = [loads]

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
            f'    bool_flag(name = "no-{feature}", build_setting_default = False,'
            f' visibility = ["//visibility:public"])\n'
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
            f'        visibility = ["//visibility:public"],\n'
            f"    )\n"
        )
    lines.append("\n")

    # openssl_pregen_config_settings macro
    lines.append(_render_pregen_config_settings_macro(known_platforms or []))

    (constants_dir / "features.bzl").write_text("".join(lines))


_WINDOWS_CONFIG_NAMES = frozenset({"windows_arm64", "windows_x64"})


def _render_pregen_config_settings_macro(known_platforms: list[str]) -> str:
    """Render the openssl_pregen_config_settings() Starlark macro.

    Four tiers of config_settings:

      _pregen_asm_<plat> (non-Windows; os+cpu + pregen=True + noasm=False)
         specialises ↓
      _asm_<plat>        (all known; os+cpu + noasm=False)
         mutually exclusive with ↓
      _no_asm_fallback   (noasm=True)

      _pregen_<plat>     (all known; os+cpu + pregen=True)
         Used only for include-path routing, independent of asm mode.

    Windows is excluded from _pregen_asm_* because its assembly is
    generated at build time via perl_genrule.
    """
    if not known_platforms:
        return "def openssl_pregen_config_settings():\n    pass\n"

    lines = [
        "def openssl_pregen_config_settings():\n",
        '    """Create config_setting targets for assembly and pre-generated file routing."""\n',
    ]

    # _no_asm_fallback: forces no-asm C fallback on any platform.
    lines.append(
        "    native.config_setting(\n"
        '        name = "_no_asm_fallback",\n'
        '        flag_values = {"//:use-no-asm-fallback": "True"},\n'
        '        visibility = ["//visibility:public"],\n'
        "    )\n"
    )

    # _use_pregenerated
    lines.append(
        "    native.config_setting(\n"
        '        name = "_use_pregenerated",\n'
        '        flag_values = {"//:use-pregenerated": "True"},\n'
        '        visibility = ["//visibility:public"],\n'
        "    )\n"
    )

    # _known_platform: match_any of all known platforms (same package)
    match_any_items = ", ".join(f'":{p}"' for p in known_platforms)
    lines.append(
        f"    selects.config_setting_group(\n"
        f'        name = "_known_platform",\n'
        f"        match_any = [{match_any_items}],\n"
        f'        visibility = ["//visibility:public"],\n'
        f"    )\n"
    )

    # _pregen_enabled: flag=True AND known platform (includes Windows for
    # template/header routing even though Windows assembly is not pre-generated).
    lines.append(
        "    selects.config_setting_group(\n"
        '        name = "_pregen_enabled",\n'
        '        match_all = [":_use_pregenerated", ":_known_platform"],\n'
        '        visibility = ["//visibility:public"],\n'
        "    )\n"
    )

    # _asm_<platform>: all known platforms, gated on no-asm-fallback=False.
    for platform in known_platforms:
        constraints = PLATFORM_CONSTRAINTS.get(platform)
        if not constraints:
            continue
        os_label, cpu_label = constraints
        lines.append(
            f"    native.config_setting(\n"
            f'        name = "_asm_{platform}",\n'
            f'        constraint_values = ["{os_label}", "{cpu_label}"],\n'
            f'        flag_values = {{"//:use-no-asm-fallback": "False"}},\n'
            f'        visibility = ["//visibility:public"],\n'
            f"    )\n"
        )

    # _pregen_<platform>: header/include routing (use-pregenerated=True only).
    # Used in the includes select to add platform-specific include paths
    # regardless of the asm/no-asm mode.
    for platform in known_platforms:
        constraints = PLATFORM_CONSTRAINTS.get(platform)
        if not constraints:
            continue
        os_label, cpu_label = constraints
        lines.append(
            f"    native.config_setting(\n"
            f'        name = "_pregen_{platform}",\n'
            f'        constraint_values = ["{os_label}", "{cpu_label}"],\n'
            f'        flag_values = {{"//:use-pregenerated": "True"}},\n'
            f'        visibility = ["//visibility:public"],\n'
            f"    )\n"
        )

    # _pregen_asm_<platform>: pre-generated assembly routing (non-Windows).
    # Requires use-pregenerated=True AND use-no-asm-fallback=False.
    # Specialises _asm_<platform> in the srcs select.
    for platform in known_platforms:
        if platform in _WINDOWS_CONFIG_NAMES:
            continue
        constraints = PLATFORM_CONSTRAINTS.get(platform)
        if not constraints:
            continue
        os_label, cpu_label = constraints
        lines.append(
            f"    native.config_setting(\n"
            f'        name = "_pregen_asm_{platform}",\n'
            f'        constraint_values = ["{os_label}", "{cpu_label}"],\n'
            f'        flag_values = {{"//:use-pregenerated": "True", "//:use-no-asm-fallback": "False"}},\n'
            f'        visibility = ["//visibility:public"],\n'
            f"    )\n"
        )

    return "".join(lines)


def perlasm_only(
    openssl_source_dir: str,
    output_dir: str,
    flavors: list[str],
    perl_path: str = "perl",
) -> None:
    """Generate only perlasm assembly for the requested flavors.

    This mode is used by platform-specific CI runners (macOS, Windows) that
    produce assembly with native compiler probing.  The output is later
    merged into the full overlay produced by the core Linux runner.
    """
    openssl_dir = Path(openssl_source_dir)
    out = Path(output_dir)

    print(f"Using Perl: {perl_path}")
    print(f"Perlasm-only mode: flavors={flavors}")

    source_platforms = {_PERLASM_FLAVORS[f]["source_platform"] for f in flavors if f in _PERLASM_FLAVORS}

    platform_data: dict[str, PlatformData] = {}
    for sp in source_platforms:
        print(f"  Configuring for {sp}...")
        platform_data[sp] = extract_platform_data(openssl_dir, sp, perl_path=perl_path)

    print("=== Pre-generating perlasm assembly ===")
    pregenerate_perlasm(openssl_dir, platform_data, out, perl_path=perl_path, flavors=flavors)

    print("=== Done (perlasm-only) ===")
    print(f"Assembly written to: {out / 'generated' / 'asm'}")


def main(
    openssl_source_dir: str,
    output_dir: str,
    bcr_dir: str | None,
    tag: str | None,
    buildifier_path: str,
    source_archive: str | None = None,
    perl_path: str = "perl",
) -> None:
    openssl_dir = Path(openssl_source_dir)
    out = Path(output_dir)

    print(f"Using Perl: {perl_path}")

    constants_dir = out / "bazel" / "constants"
    constants_dir.mkdir(parents=True, exist_ok=True)

    platform_data: dict[str, PlatformData] = {}

    print("=== Extracting source lists for all platforms ===")
    for platform in ALL_PLATFORMS:
        config_name = get_simple_config_name(platform)
        print(f"  Configuring for {platform} ({config_name})...")
        data = extract_platform_data(openssl_dir, platform, perl_path=perl_path)
        platform_data[platform] = data

    print("  Configuring for no-asm fallback...")
    no_asm_data = extract_platform_data(openssl_dir, NO_ASM_TARGET, perl_path=perl_path)

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

    # Known platform config_names for pregen routing.
    known_platforms = sorted(get_simple_config_name(p) for p in ALL_PLATFORMS)

    print("=== Generating feature toggle flags ===")
    write_features_bzl(constants_dir, user_features, known_platforms)

    print("=== Generating per-platform configdata stubs ===")
    generate_configdata_stubs(platform_data, no_asm_data, out)

    print("=== Pre-generating template outputs ===")
    pregenerate_templates(openssl_dir, platform_data, out, perl_path=perl_path)

    # Place configdata in the source tree so $_repo_root resolves correctly.
    any_config = get_simple_config_name(next(iter(platform_data)))
    try:
        local_configdata = _place_configdata_in_source(
            openssl_dir,
            out / "configdata" / any_config,
            any_config,
        )
        print("=== Pre-generating progs.h/progs.c ===")
        pregenerate_progs(openssl_dir, out, local_configdata, perl_path=perl_path)
    finally:
        _cleanup_source_configdata(openssl_dir)

    print("=== Pre-generating buildinf.h ===")
    generate_buildinf_h(out)

    print("=== Pre-generating perlasm assembly ===")
    pregenerate_perlasm(openssl_dir, platform_data, out, perl_path=perl_path)

    # Overlay root = out. All overlay files go under out for correct load paths.
    overlay_dir = out
    copy_from_here_to("BUILD.openssl.bazel", overlay_dir / "BUILD.bazel")
    (overlay_dir / "configs").mkdir(parents=True, exist_ok=True)
    copy_from_here_to("BUILD.configs.bazel", overlay_dir / "configs" / "BUILD.bazel")
    copy_from_here_to("perl_genrule.bzl", overlay_dir / "bazel" / "perl_genrule.bzl")
    copy_from_here_to("openssl_genrule.bzl", overlay_dir / "bazel" / "openssl_genrule.bzl")
    copy_from_here_to("pregen.bzl", overlay_dir / "bazel" / "pregen.bzl")
    copy_from_here_to("redirect_stdout.cc", overlay_dir / "bazel" / "redirect_stdout.cc")
    copy_from_here_to("batch_dofile.pl", overlay_dir / "bazel" / "batch_dofile.pl")
    copy_from_here_to("BUILD.bazel.bazel", overlay_dir / "bazel" / "BUILD.bazel")
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
        bazel_dep(name = "rules_perl", version = "1.1.0")
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
    parser.add_argument(
        "--buildifier",
        default=None,
        help="Path to buildifier (auto-detected from Bazel toolchain or PATH if omitted; pass empty string to skip)",
    )
    parser.add_argument("--source_archive", required=False, help="Path to source tarball for BCR integrity hash")
    parser.add_argument(
        "--perl",
        default=None,
        help="Path to Perl interpreter (auto-detected from Bazel toolchain or PATH if omitted)",
    )
    parser.add_argument(
        "--perlasm-only",
        default=None,
        dest="perlasm_only",
        help="Comma-separated perlasm flavors (e.g. 'masm,win64'). "
        "Only runs perlasm pre-generation for the specified flavors, "
        "then exits. Used by platform-native CI runners.",
    )
    args = parser.parse_args()
    perl = _resolve_perl(args.perl)

    if args.perlasm_only:
        perlasm_only(
            args.openssl_source_dir,
            args.output_dir,
            flavors=args.perlasm_only.split(","),
            perl_path=perl,
        )
    else:
        buildifier = _resolve_buildifier(args.buildifier)
        print(f"Resolved buildifier: {buildifier or '(skipped)'}")
        main(
            args.openssl_source_dir,
            args.output_dir,
            args.bcr_dir,
            args.tag,
            buildifier,
            args.source_archive,
            perl_path=perl,
        )
