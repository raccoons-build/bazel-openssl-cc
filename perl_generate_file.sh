#!/bin/bash

set -euo pipefail

if [[ "$#" -ne 4 ]]; then
  echo "Need four params"
  exit 1
fi

binary_invocation="$1"
src_file="$2"
out_file="$3"
assembly_generator_invocation="$4"

echo ${binary_invocation} ${src_file} ${assembly_generator_invocation} ${out_file}
if test -f ${out_file}; then
  echo "${out_file} exists"
else
  echo "${out_file} does not exist failing"
  exit 1
fi

exit 0
