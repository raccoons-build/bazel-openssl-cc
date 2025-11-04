#!/bin/bash

set -euo pipefail

case "$(uname)" in
  "Darwin")
    suffix="darwin-amd64"
    out_file="/tmp/buildifier.exe"
    ;;
  "Linux")
    suffix="linux-amd64"
    out_file="/tmp/buildifier.exe"
    ;;
  "MINGW64_NT-10.0-20348")
    suffix="windows-amd64.exe"
    out_file="C:\\buildifier.exe"
    ;;
  *)
    echo >&2 "Unknown uname $(uname)"
    exit 1
    ;;
esac

curl --fail -L -o "${out_file}" "https://github.com/bazelbuild/buildtools/releases/download/v8.2.1/buildifier-${suffix}"
chmod 0755 "${out_file}"
