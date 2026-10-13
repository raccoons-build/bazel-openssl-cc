# Security Policy

## Scope

This repository ships a Bazel build description for OpenSSL, plus files
produced by OpenSSL's own generator scripts. It does not modify OpenSSL's
source code. A security issue in this project is a packaging defect, such as:

- a build configuration that disables a protection OpenSSL enables by
  default, or defines a platform incorrectly;
- a pre-generated file that differs from what OpenSSL's build would produce;
- a release archive or source reference whose integrity hash does not match
  what was tested;
- a workflow that could be made to publish a tampered release.

Vulnerabilities in OpenSSL itself are handled by the OpenSSL project under its
[security policy]. Do not report them here: this project cannot fix them and
picks them up by publishing the fixed OpenSSL version.

## Reporting

Report packaging issues privately through [GitHub security advisories] for
this repository. Do not open a public issue. Include the module version (for
example `4.0.1.bcr.0`), the platform and Bazel version, and steps to reproduce.

## Supported versions

Fixes are published as a new revision (`<openssl version>.bcr.N`) of the
OpenSSL versions listed under "Supported versions" in the [README](README.md).
Earlier revisions are not patched; update to the newest revision of your
OpenSSL version.

## No warranty

This project is maintained by volunteers and distributed under the Apache
License 2.0, which disclaims all warranties and liability (sections 7 and 8 of
[LICENSE.txt](LICENSE.txt)). Reports are handled in good faith with no
guaranteed response time.

[security policy]: https://openssl-library.org/policies/general/security-policy/
[GitHub security advisories]: https://github.com/raccoons-build/bazel-openssl-cc/security/advisories/new
