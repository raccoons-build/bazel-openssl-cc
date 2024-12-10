#!/bin/bash

set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  echo >&2 "Usage: /dest/dir file prefix"
  exit 1
fi

dest_dir="$1"
file="$2"
prefix="$3"
clean_filepath="${file##$prefix}"
clean_dirname="$(dirname ${clean_filepath})"

mkdir -p "${dest_dir}/${clean_dirname}"
cp -RL "${file}" "${dest_dir}/${clean_dirname}"
