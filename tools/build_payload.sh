#!/bin/sh
# Run on the home PC with its existing SDK. No dependency installation.
set -eu
: "${PS5_PAYLOAD_SDK:?Set PS5_PAYLOAD_SDK to the existing SDK directory}"
cd "$(dirname "$0")/.."
if [ -n "${SPOTLESS_LLVM_BINDIR:-}" ]; then
    export SPOTLESS_LLVM_BINDIR
    export LLVM_CONFIG="$PWD/tools/sdk_llvm_config.sh"
fi
"$PS5_PAYLOAD_SDK/bin/prospero-clang" -std=c11 -O2 -Wall -Wextra -Werror \
    payload/watcher.c -o payload/Spotless.elf
"$PS5_PAYLOAD_SDK/bin/prospero-clang" -std=c11 -O2 -Wall -Wextra -Werror -Wno-unused-function \
    -DSPOTLESS_RESTORE payload/watcher.c -o payload/Spotless-Restore.elf
