# Per-version overrides

Most OpenSSL releases need no changes here: the generator derives what varies between
versions from OpenSSL's own `configdata.pm`. When a version really needs different overlay
logic, put only the differing files in a directory named after it, mirroring the
repository layout:

```
versions/
  3/        every 3.x.y release    e.g. overlay/BUILD.bazel
  3.5/      every 3.5.y release    e.g. overlay/bazel/pregen.bzl
  4.0.1/    exactly 4.0.1          e.g. generator/configdata.pm.in
```

Lookup is per file, most specific first: `MAJOR.MINOR.PATCH`, `MAJOR.MINOR`, `MAJOR`, then
the repository root. Files under `overlay/` and `pregen/` may also be added; files under
`.bcr/` and `generator/` must replace an existing one. Anything outside those four trees,
or a directory not named like a version, is an error.

Prefer making the shared files handle both cases, e.g. `glob(..., allow_empty = True)` or
data extracted by the generator: every override is another copy to keep in sync. The
generator prints the overrides in effect at the start of each run.
