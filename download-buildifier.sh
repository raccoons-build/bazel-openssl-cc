#!/bin/bash

set -euo pipefail

case "$(uname)" in
  "Darwin")
    suffix="darwin-amd64"
    ;;
  "Linux")
    suffix="linux-amd64"
    ;;
  "MINGW64_NT-10.0-20348")
    suffix="windows-amd64"
    ;;
  *)
    echo >&2 "Unknown uname $(uname)"
    exit 1
    ;;
esac

curl --fail -L -o /tmp/buildifier.exe "https://github.com/bazelbuild/buildtools/releases/download/v7.3.1/buildifier-${suffix}"
chmod 0755 /tmp/buildifier.exe
