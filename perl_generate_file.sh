#!/bin/bash

set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  echo "Need a param"
  exit 1
fi

commands="$1"
echo "Running ${commands}"
# Iterate over each command separated by comma
IFS=',' read -ra commands_arr <<< "$commands"
for command in "${commands_arr[@]}"; do
    ${command}

    # Get the last element of the command, the out file
    # and check for existence.
    IFS=' ' read -ra split_command_arr <<< "${command}"
    out_file="${split_command_arr[3]}"
    if test -f ${out_file}; then
      echo "${out_file} exists"
    else
      echo "${out_file} does not exist failing"
      exit 1
    fi
done

if [[ "$OSTYPE" == "darwin"* ]]; then
  ls bazel-out/darwin_arm64-fastbuild/bin/external/openssl+/crypto/sha
else
  tree bazel-out/k8-fastbuild/bin/external/openssl+
fi

exit 0