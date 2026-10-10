# Per-version overrides

The generator produces the overlay for whatever OpenSSL version it is pointed
at, reading the version from the source tree's `VERSION.dat`. Everything that
is known to differ between versions is derived from OpenSSL's own build
description (`configdata.pm`): source lists, defines, the set of
`util/dofile.pl` templates, which generated headers vary by platform, and so
on. So most OpenSSL releases need no changes here at all.

When a version does need different overlay logic, put the differing files in
a directory named after the version, mirroring the repository layout:

```
versions/
  3/                        applies to every 3.x.y release
    overlay/BUILD.bazel
  3.5/                      applies to every 3.5.y release
    overlay/bazel/pregen.bzl
  4.0.1/                    applies to exactly 4.0.1
    generator/configdata.pm.in
```

Resolution is per file, most specific directory first:
`versions/<MAJOR.MINOR.PATCH>/`, then `versions/<MAJOR.MINOR>/`, then
`versions/<MAJOR>/`, then the repository root. An override directory only
needs to contain the files that differ. Files under `overlay/` and `pregen/`
may also be *added* (they are copied into the output alongside the defaults);
files under `generator/` must replace an existing input.

Prefer teaching the shared files to handle both cases (for example with
`glob(..., allow_empty = True)` or data extracted by the generator) over
adding an override. Overrides are the escape hatch for the cases where that
is not practical, since every overridden file is one more copy to keep in
sync.

The generator prints the override directories in effect at the start of a
run, and fails if an override contains a path outside `generator/`,
`overlay/` or `pregen/`.
