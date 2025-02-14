#!/bin/bash

set -euo pipefail

if [[ "$#" -ne 4 ]]; then
  echo "Need four params"
  exit 1
fi

binary_invocation="$1"
src_file="$2"
out_file="$3"
assembly_flavor="$4"

${binary_invocation} ${src_file} ${assembly_flavor} ${out_file}

tree bazel-out/k8-fastbuild/bin/external/openssl+

if test -f ${out_file}; then
  echo "${out_file} exists"
else
  echo "${out_file} does not exist failing"
  exit 1
fi

exit 0