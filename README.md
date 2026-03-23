# bazel-openssl-cc

[![Build & Test](https://github.com/raccoons-build/bazel-openssl-cc/actions/workflows/pr.yaml/badge.svg)](https://github.com/raccoons-build/bazel-openssl-cc/actions/workflows/pr.yaml)

Generates a bzlmod overlay to compile OpenSSL with `cc_library` targets. Based on
[`dbx_build_tools`](https://github.com/dropbox/dbx_build_tools/blob/master/thirdparty/openssl/BUILD.openssl.tail).

## Architecture

`generate_constants.py` runs OpenSSL's `Configure` for 15 target platforms + a no-asm
fallback, extracts source lists and defines, then pre-generates headers, sources, and
perlasm assembly. The output is an overlay placed on top of the OpenSSL source tree.

At build time, `select()` routes between three modes:

| Mode                        | When                                          | What happens                                                                                         |
| --------------------------- | --------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| **Pre-generated** (default) | Known platform, `use-pregenerated=True`       | `pregen_files` symlinks static files to canonical output paths. Zero Perl.                           |
| **Perl fallback**           | Unknown platform, or `use-pregenerated=False` | `openssl_perl_genrule` + `perl_genrule` run Perl via `rules_perl`. Always used for Windows assembly. |
| **No-asm**                  | `use-no-asm-fallback=True`                    | Portable C only. No assembly, no Perl.                                                               |

Both pregen and Perl paths produce outputs at identical canonical paths (e.g.
`include/openssl/bio.h`), so downstream targets need no mode-specific include paths.

## Build Flags

```
--@openssl//:use-pregenerated=False    # Force Perl genrule path
--@openssl//:use-no-asm-fallback=True  # Force portable C, no assembly
```

## Regenerating the Overlay

Requires Bazel 7+, a C compiler, and optionally `nasm` for MASM perlasm.

```bash
bazel run //:generate -- \
  --openssl_source_dir /path/to/openssl \
  --output_dir /path/to/output
```

Standalone (needs system Python 3.10+, Perl 5, buildifier):

```bash
python3 generate_constants.py \
  --openssl_source_dir /path/to/openssl \
  --output_dir /path/to/output
```

## Testing

Write the overlay directly into the OpenSSL source tree, then build:

```bash
bazel run //:generate -- \
  --openssl_source_dir /path/to/openssl \
  --output_dir /path/to/openssl

cd /path/to/openssl
bazel test //test_bazel_build/...
bazel build //... --@openssl//:use-pregenerated=False   # test Perl path
bazel build //... --@openssl//:use-no-asm-fallback=True  # test no-asm path
```
