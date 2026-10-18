# Development

## Layout

| Path | Contents |
| --- | --- |
| `payload/` | Native watcher: readiness checks, checksums, atomic cache writes |
| `frontend/standalone/` | Frontend shim, pinned generated bundle and browser tests |
| `frontend/cache-analysis/` | Python reference for the WebKit cache format, with test fixtures |
| `tools/` | Build, release, package merger and console cleanup scripts |
| `tests/` | Host-side native, script and release tests |

## How it works

The payload waits up to ten minutes for Spotify's native backend and the supported
JavaScript, vendor and CSS cache records. Once they have been stable for five
seconds, it validates their checksums, writes a backup to `/data/spotless/` and
atomically swaps in the patched bundle. The payload never carries Spotify's
code: it ships a small table of insertions (`payload/ui_patch.h`) and applies them
to the console's own cached copy, then checks the result against the expected
hash before writing. A second concurrent instance will not
install again, and an already patched cache is detected and left alone.
`Spotless-Restore.elf` reverses the swap using the verified backups.

The patched frontend is generated from pinned upstream assets (`f1b1b7e`). The
shim lets the existing frontend publish a valid Spotify session without Sony
account linking; sign-in, session validation, logout and playback stay as Spotify
implemented them. Authentication identifiers you see in the bundle belong to that
normal session handling. See [frontend/standalone](../frontend/standalone/README.md).

## Build

You need a PS5 payload SDK and its LLVM toolchain:

```sh
PS5_PAYLOAD_SDK=/path/to/ps5-payload-sdk \
SPOTLESS_LLVM_BINDIR=/path/to/llvm/bin \
sh tools/build_payload.sh
```

This produces `payload/Spotless.elf` and `payload/Spotless-Restore.elf`.

After changing the shim or the edits, fetch the pinned original and regenerate the
edit table:

```sh
curl --compressed -o frontend/spotifytv.js \
  https://tv.scdn.co/ps5/v2/f1b1b7e/js/spotifytv.js
python3 frontend/standalone/build_patch.py
```

The builder rejects any other input. It writes `payload/ui_patch.h` and the
manifest (both checked in), plus a local `spotifytv.standalone.js` used by the
tests. Spotify's code is never committed.

## Tests

The full suite needs Python 3.9+, a C compiler, Clang with AddressSanitizer and
UndefinedBehaviorSanitizer, Node.js and Firefox, plus `frontend/spotifytv.js`
fetched as shown above.

```sh
python3 tests/run_checks.py
```

The tests cover cache decoding and checksums, readiness and atomic recovery, patch
determinism, browser session handling, CRC32C package verification, cleanup
scoping and release contents. Cleanup tests use mocked services and never touch a
real console.

Console testing so far: the payload on firmware 13.00 with Spotify 01.017.000, and
the cleanup preview over FTP. The destructive cleanup path has only been tested
against mocks.

## Release

Build, then publish into a new, empty directory:

```sh
python3 tools/build_release.py --output-dir dist/release
```

Upload the ELFs, checksums, metadata and `SHA256SUMS` as release assets. The
script refuses a non-empty output directory so stale files cannot slip in.
It also refuses an ELF that embeds Spotify's frontend. Releases never contain
PKGs, credentials or console captures.

## Contributing

- Keep changes focused and describe how you tested them, including any console
  testing still needed.
- Never bypass the frontend hash checks, atomic replacement or backup validation.
- Never commit credentials, PKGs or captures from your own console.

Contributions are accepted under the [GPL-3.0](../LICENSE).
