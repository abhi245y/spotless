#!/bin/sh
# Minimal adapter for the existing SDK wrapper when llvm-config is absent.
set -eu
: "${SPOTLESS_LLVM_BINDIR:?Point SPOTLESS_LLVM_BINDIR at existing LLVM bin directory}"
case "${1:-}" in
    --bindir) printf '%s\n' "$SPOTLESS_LLVM_BINDIR" ;;
    --version) "$SPOTLESS_LLVM_BINDIR/clang" -dumpversion ;;
    *) echo 'Only --bindir and --version are supported' >&2; exit 1 ;;
esac
