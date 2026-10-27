# bazel-openssl-cc

[![Build & Test](https://github.com/raccoons-build/bazel-openssl-cc/actions/workflows/pr.yaml/badge.svg)](https://github.com/raccoons-build/bazel-openssl-cc/actions/workflows/pr.yaml)

Generates a bzlmod overlay to compile OpenSSL with `cc_library` targets. Based on
[`dbx_build_tools`](https://github.com/dropbox/dbx_build_tools/blob/master/thirdparty/openssl/BUILD.openssl.tail).

## Repository layout

| Directory    | Contents                                                                                            |
| ------------ | --------------------------------------------------------------------------------------------------- |
| `generator/` | `//generator:generate` and its inputs (`extract_srcs.pl`, `configdata.pm.in`, `buildinf.h.in`).     |
| `overlay/`   | The BCR overlay in its shipped layout. `MODULE.bazel` is a template; the rest is copied as is.      |
| `pregen/`    | Root of the pre-generated archive attached to GitHub releases.                                      |
| `versions/`  | Per-OpenSSL-version overrides of the above; see [versions/README.md](versions/README.md).           |

`overlay/`, `pregen/` and `versions/` are in `.bazelignore`: their `BUILD.bazel` files are
templates, not packages of this repository.

## Supported versions

The focus of this repository is OpenSSL's **long-term support** releases: the LTS line
(currently 3.5, supported upstream until April 2030) is what gets released here first and
kept green. The current non-LTS release line is supported as well, and any 3.0 or later
release can be generated.

| Line     | Upstream status                | Here                                                  |
| -------- | ------------------------------ | ----------------------------------------------------- |
| 3.5 LTS  | Supported until 2030-04        | Primary target; in the pull request matrix.           |
| 4.0      | Current release, 1-year support | In the pull request matrix.                            |
| 3.0 LTS  | End of life 2026-09-07         | Still builds (verified with 3.0.22); not in the matrix. |
| `master` | Development                    | Built nightly to catch upcoming changes early.         |

The generator takes an OpenSSL source tree and reads its version from `VERSION.dat`.
Everything that varies between releases comes from OpenSSL's own `configdata.pm`: source
lists, defines, the `util/dofile.pl` templates, and which generated headers differ per
platform (found by rendering each template for every platform and comparing). A version
that needs different overlay logic gets a `versions/` override, not a branch.

Pull requests build and test every version in
[`.github/openssl-versions.json`](.github/openssl-versions.json); a nightly job does the
same against upstream `master`. Releases are tags of the form `<OPENSSL_VERSION>.bcr.<N>`;
see [Releasing](#releasing).

## Architecture

`generator/generate_constants.py` runs OpenSSL's `Configure` for 15 target platforms plus a
no-asm fallback, extracts source lists and defines, and pre-generates headers, sources and
perlasm assembly. It outputs an overlay for the OpenSSL source tree and a separate
pre-generated archive.

The module builds from the upstream source archive and the overlay alone: with
`--@openssl//:use-pregenerated=False` all code generation runs OpenSSL's own Perl scripts
at build time and nothing is fetched from this repository. The pre-generated archive only
removes Perl from the default build.

At build time, `select()` routes between three modes:

| Mode                        | When                                          | What happens                                                                                         |
| --------------------------- | --------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| **Pre-generated** (default) | Known platform, `use-pregenerated=True`       | `pregen_files` symlinks static files to canonical output paths. Zero Perl.                           |
| **Perl fallback**           | Unknown platform, or `use-pregenerated=False` | `openssl_perl_genrule` + `openssl_perlasm` run Perl via `rules_perl`.                                |
| **No-asm**                  | `use-no-asm-fallback=True`                    | Portable C only. No assembly, no Perl.                                                               |

Platforms are identified by OS and CPU, plus the compiler on Windows. glibc is
assumed on Linux and MSVC on Windows (the pre-generated Windows assembly is
MASM flavoured; mingw builds need `use-pregenerated=False`). libc constraints
could come from [platforms_contrib](https://github.com/bazel-contrib/platforms_contrib/)
in the future.

Both pregen and Perl paths produce outputs at identical canonical paths (e.g.
`include/openssl/bio.h`), so downstream targets need no mode-specific include paths.

The perlasm scripts pick instruction-set paths by probing `$CC`. The Perl path probes the
configured `cc_toolchain` compiler. The pre-generated path answers the probes with pinned
values (GNU as 2.38 for `elf`/`linux64`, clang 15 for `macosx`/`ios64`; see
`_PERLASM_PROBE_PROFILES`), so the shipped assembly does not depend on where it was
generated. Those versions are its minimum assembler requirement; older toolchains should
use `use-pregenerated=False`.

## Build Flags

```
--@openssl//:use-pregenerated=False    # Force Perl genrule path
--@openssl//:use-no-asm-fallback=True  # Force portable C, no assembly
```

## Releasing

A release is a tag `<OPENSSL_VERSION>.bcr.<N>`, e.g. `4.0.1.bcr.3`: upstream OpenSSL 4.0.1,
revision 3 of this overlay for it (revisions start at 0).
[`release.yaml`](.github/workflows/release.yaml) runs the same pipeline however it starts:

- **Manually (recommended):** Actions -> Release -> Run workflow. Pick the branch (normally
  `main`) and enter the release, e.g. `4.0.1.bcr.3`, or just `4.0.1` for the next unused
  revision. Several releases can be cut in one run, comma separated, e.g. `3.5.4,4.0.1`:
  each gets its own tag and GitHub release, and the registry gets a single pull request
  titled `openssl@3.5.4.bcr.0, openssl@4.0.1.bcr.0`, so the registry changes never conflict
  with each other. The tags are created at the end, only after every job has passed.
- **By tag:** push the tag. To re-run an existing tag, run the workflow on that tag with the
  release field empty.

The pipeline:

1. Download `openssl-<version>.tar.gz` and run the generator, which refuses a tag that does
   not match `VERSION.dat`.
2. Package the pre-generated archive and register the module in a scratch copy of the Bazel
   Central Registry, once with the GitHub release URL and once with a local `file://` copy
   for testing.
3. Build and test `@openssl//...` from the local copy on Linux x86_64 and arm64, macOS and
   Windows, with Bazel 7, 8 and 9, in both modes, with `--incompatible_auto_exec_groups`.
   This is the pull request matrix.
4. Assemble the registry change (every module version plus their `metadata.json` entries,
   in one commit) and run the registry's `bcr_validation.py` on it.
5. Create each tag if needed, upload `bazel-openssl-cc-<tag>.tar.gz` as a release asset, and
   open one pull request to publish the modules on the Bazel Central Registry, from the
   branch `openssl-release-<run number>` of the fork.

Steps 1 to 3 run per version, in parallel; steps 4 and 5 run once, and only after every
version has passed. If anything fails, nothing is published and no tag is created: re-run
the failed jobs (same run, same registry branch), or fix `main` and release again, leaving
out a version that needs more work. Tags are never reused. Creating the tags needs
`contents: write`; if a tag protection rule blocks `GITHUB_TOKEN`, push the tag by hand
and re-run on it.

**Nightly.** [`nightly.yaml`](.github/workflows/nightly.yaml) runs steps 1 to 4 every night
against a snapshot of the current upstream `master` commit. A red nightly means the next
OpenSSL release will need overlay changes.

**Supported versions.** Before releasing a version this repository has not built, add it to
[`.github/openssl-versions.json`](.github/openssl-versions.json) and open a pull request;
that runs the pipeline without publishing and surfaces any version-specific breakage (see
[versions/README.md](versions/README.md)). Keep every version you still release in that
list.

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

A build only exercises the current platform's `select()` branches. To check
that the source files named by every branch exist in this OpenSSL version,
run `.github/scripts/check_source_files.sh` from a workspace that depends on
the module; CI does this on every pull request.
