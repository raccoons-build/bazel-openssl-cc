#!/usr/bin/env bash
# Usage: check_source_files.sh [bazel flags...]
#
# Checks, from a workspace that depends on the openssl module, that every
# source file the overlay refers to exists in the OpenSSL source tree.
#
# Bazel only notices a missing source file when an action needs it, so a
# stale path in a select() branch (crypto/LPdir_wince.c, gone in 4.1) fails
# only on the one platform that compiles it. `bazel query` is unconfigured
# and lists the source files of every branch, so one run covers all
# platforms.
set -euo pipefail

output_base=$(bazel info "$@" output_base)
labels=$(mktemp)
trap 'rm -f "$labels"' EXIT
# --consistent_labels prints canonical repository names, so the module's own
# files come out as @@openssl+//:crypto/foo.c (@@openssl~ on Bazel 7), which
# lives at <output_base>/external/openssl+/crypto/foo.c.
bazel query "$@" --consistent_labels 'kind("source file", deps(@openssl//...))' --output=label \
    | grep -E '^@@openssl[+~]//:' > "$labels"
test -s "$labels" || { echo "no openssl source files found; is this a workspace depending on the openssl module?"; exit 1; }

missing=0
while IFS= read -r label; do
    repo=${label#@@}
    repo=${repo%%//*}
    path=${label#*//:}
    if [ ! -e "${output_base}/external/${repo}/${path}" ]; then
        echo "missing source file: ${label}"
        missing=1
    fi
done < "$labels"
echo "checked $(wc -l < "$labels") source files"
exit "${missing}"
