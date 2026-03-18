# bazel-openssl-cc

[![Build & Test](https://github.com/raccoons-build/bazel-openssl-cc/actions/workflows/pr.yaml/badge.svg)](https://github.com/raccoons-build/bazel-openssl-cc/actions/workflows/pr.yaml)

Scripts for generating a bzlmod module to compile openssl using cc_library targets.

This code is heavily based on the implementation in [`dbx_build_tools`](https://github.com/dropbox/dbx_build_tools/blob/master/thirdparty/openssl/BUILD.openssl.tail).

The entry-point is `generate_constants.py`. It runs OpenSSL's `Configure` for all
target platforms on a single machine (no `make` needed), extracts source lists via
`extract_srcs.pl`, and produces a tiered overlay with `//conditions:default` fallback
for unknown platforms.
