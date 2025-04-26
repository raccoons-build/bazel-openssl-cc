# bazel-openssl-cc

[![Build & Test](https://github.com/raccoons-build/bazel-openssl-cc/actions/workflows/pr.yaml/badge.svg)](https://github.com/raccoons-build/bazel-openssl-cc/actions/workflows/pr.yaml)

Scripts for generating a bzlmod module to compile openssl using cc_library targets.

This code is heavily based on the implementation in [`dbx_build_tools`](https://github.com/dropbox/dbx_build_tools/blob/master/thirdparty/openssl/BUILD.openssl.tail).

The entry-point is `generate_per_platform.py` and `generate_combine_platforms.py`.
