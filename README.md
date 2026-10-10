# bazel-openssl-cc

[![Build & Test](https://github.com/raccoons-build/bazel-openssl-cc/actions/workflows/pr.yaml/badge.svg)](https://github.com/raccoons-build/bazel-openssl-cc/actions/workflows/pr.yaml)

Generates a bzlmod overlay to compile OpenSSL with `cc_library` targets. Based on
[`dbx_build_tools`](https://github.com/dropbox/dbx_build_tools/blob/master/thirdparty/openssl/BUILD.openssl.tail).

## Repository layout

| Directory    | Contents                                                                                                   |
| ------------ | ---------------------------------------------------------------------------------------------------------- |
| `generator/` | The `//generator:generate` binary and its inputs (`extract_srcs.pl`, `configdata.pm.in`, `buildinf.h.in`). |
| `overlay/`   | The BCR overlay, same layout: `MODULE.bazel` (rendered), `BUILD.bazel`, `bazel/*.bzl`, `configs/BUILD.bazel`. |
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

Releases are driven by git tags of the form `<OPENSSL_VERSION>.bcr.<N>`; see
[Releasing](#releasing). Pull requests regenerate and test every version listed in the
matrix in [`.github/workflows/pr.yaml`](.github/workflows/pr.yaml). Add a version there
to start supporting it.

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
| **Perl fallback**           | Unknown platform, or `use-pregenerated=False` | `openssl_perl_genrule` + `openssl_perlasm` run Perl via `rules_perl`. Always used for Windows assembly. |
| **No-asm**                  | `use-no-asm-fallback=True`                    | Portable C only. No assembly, no Perl.                                                               |

Both pregen and Perl paths produce outputs at identical canonical paths (e.g.
`include/openssl/bio.h`), so downstream targets need no mode-specific include paths.

The perlasm scripts choose instruction-set paths by probing `$CC`. In the Perl path that
is the configured `cc_toolchain` compiler, so the result matches the toolchain actually
assembling the output. In the pre-generated path the generator answers those probes with
pinned values instead of a real compiler (GNU as 2.38 for `elf`/`linux64`, clang 15 for
`macosx`/`ios64`; see `_PERLASM_PROBE_PROFILES`), so the shipped assembly is identical no
matter where it was generated and those are the minimum assemblers it requires. Older
toolchains should build with `--@openssl//:use-pregenerated=False`.

## Build Flags

```
--@openssl//:use-pregenerated=False    # Force Perl genrule path
--@openssl//:use-no-asm-fallback=True  # Force portable C, no assembly
```

## Releasing

A release is identified by a git tag `<OPENSSL_VERSION>.bcr.<N>`, for example `4.0.3.bcr.0`
or `3.6.5.bcr.1`. The OpenSSL version is taken from the tag; `N` is this repository's
revision of the overlay for that OpenSSL version and starts at 0. Both ways of starting a
release run the same pipeline, [`release.yaml`](.github/workflows/release.yaml).

**Manually (recommended).** In GitHub, Actions → Release → Run workflow. Choose the branch
to release from (normally `main`) and enter the OpenSSL version, e.g. `4.0.3`. Leave the
revision empty to get the next unused `.bcr.<N>` for that version, or set it explicitly.
The tag is created at the end of the run, at the commit you chose, and only once every
build and test job has passed.

**By tag.** Pushing a `<version>.bcr.<N>` tag runs the same pipeline against that commit.
To re-run the release for an existing tag, run the workflow manually *on that tag* (pick
it in the "Use workflow from" selector) and leave the version empty.

The pipeline:

1. Downloads the matching `openssl-<version>.tar.gz` from GitHub and runs the generator
   against it (the generator reads `VERSION.dat` and refuses a tag that names a different
   version).
2. Packages the pre-generated archive and registers the module in a scratch copy of the
   Bazel Central Registry, twice: once pointing at the GitHub release URL that the release
   will create, once pointing at a local `file://` copy of the archive.
3. Builds and tests `@openssl//...` from the local-copy registry on Linux x86_64 and arm64,
   macOS and Windows, with Bazel 7, 8 and 9, in both the pre-generated and the from-source
   (`--@openssl//:use-pregenerated=False`) modes, all with `--incompatible_auto_exec_groups`.
   This is the same matrix pull requests run.
4. Only if every job above passed: creates the tag if it does not exist yet, uploads
   `bazel-openssl-cc-<tag>.tar.gz` as a GitHub release asset, and opens a pull request
   against `bazelbuild/bazel-central-registry` from the `illicitonion` fork (using the
   `BCR_GITHUB_TOKEN` secret), adding the module version and its `metadata.json` entry.

If any step fails, nothing is published and no tag is created. Published tags are not
reused: fix the problem on `main` and release again, which picks the next `.bcr.<N>`.
Creating the tag needs the workflow's `contents: write` permission; a tag protection rule
that excludes `GITHUB_TOKEN` would make the final step fail, in which case push the tag by
hand and re-run on it.

Before releasing an OpenSSL version this repository has not built before, add it to the
version matrix in [`pr.yaml`](.github/workflows/pr.yaml) and open a pull request. That runs
the same generate-and-test pipeline without publishing anything, and is where any
version-specific breakage shows up (see [versions/README.md](versions/README.md) for how
to handle it). Keep the versions you intend to keep releasing in that matrix so later
changes to the overlay are checked against all of them.

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
