# bazel-openssl-cc

[![Build & Test](https://github.com/raccoons-build/bazel-openssl-cc/actions/workflows/pr.yaml/badge.svg)](https://github.com/raccoons-build/bazel-openssl-cc/actions/workflows/pr.yaml)

Generates a bzlmod overlay to compile OpenSSL with `cc_library` targets. Based on
[`dbx_build_tools`](https://github.com/dropbox/dbx_build_tools/blob/master/thirdparty/openssl/BUILD.openssl.tail).

## Repository layout

| Directory    | Contents                                                                                                   |
| ------------ | ---------------------------------------------------------------------------------------------------------- |
| `generator/` | The `//generator:generate` binary and its inputs (`extract_srcs.pl`, `configdata.pm.in`, `buildinf.h.in`). |
| `overlay/`   | Copied verbatim into the BCR overlay, same layout: `BUILD.bazel`, `bazel/*.bzl`, `configs/BUILD.bazel`.    |
| `pregen/`    | Copied verbatim into the root of the pre-generated archive published on GitHub releases.                   |
| `versions/`  | Optional per-OpenSSL-version overrides of any of the above. See [versions/README.md](versions/README.md). |

`overlay/`, `pregen/` and `versions/` are listed in `.bazelignore`; their `BUILD.bazel`
files are templates, not packages of this repository.

## Supporting any OpenSSL version

Nothing in this repository pins an OpenSSL version. The generator reads the version
from `VERSION.dat` in the source tree it is given, and derives everything that varies
between releases from OpenSSL's own `configdata.pm`: source lists, defines, the set of
`util/dofile.pl` templates (`bazel/constants/templates.bzl`), and which generated
headers differ per platform (found by rendering every template for every platform and
comparing). Where a version genuinely needs different overlay logic, add a
`versions/<version>/` override rather than a branch.

Releases are driven by git tags of the form `<OPENSSL_VERSION>.bcr.<N>`, e.g.
`4.0.1.bcr.0` or `3.5.8.bcr.1`; the release workflow derives the OpenSSL version from
the tag. Pull requests regenerate and test every version listed in the matrix in
[`.github/workflows/pr.yaml`](.github/workflows/pr.yaml). Add a version there to start
supporting it.

## Architecture

`generator/generate_constants.py` runs OpenSSL's `Configure` for 15 target platforms + a
no-asm fallback, extracts source lists and defines, then pre-generates headers, sources,
and perlasm assembly. The output is an overlay placed on top of the OpenSSL source tree
plus a separate pre-generated archive.

The BCR module is fully buildable from the upstream OpenSSL source archive plus the
overlay: with `--@openssl//:use-pregenerated=False` all code generation runs through
OpenSSL's own Perl scripts at build time and nothing is fetched from this repository.
The pre-generated archive is an optimisation that removes Perl from the default build.

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
python3 generator/generate_constants.py \
  --openssl_source_dir /path/to/openssl \
  --output_dir /path/to/output
```

To also produce the BCR module files, pass `--bcr_dir`, `--source_archive` and a
`--tag` that starts with the version in the source tree's `VERSION.dat`:

```bash
bazel run //:generate -- \
  --openssl_source_dir /path/to/openssl-4.0.1 \
  --output_dir /path/to/overlay \
  --pregen_dir /path/to/pregen \
  --bcr_dir /path/to/bazel-central-registry \
  --tag 4.0.1.bcr.0 \
  --source_archive /path/to/openssl-4.0.1.tar.gz
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
