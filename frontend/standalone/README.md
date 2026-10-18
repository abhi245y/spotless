# Standalone frontend

This shim lets Spotify's existing frontend publish a valid Spotify session without
Sony account linking. Code sign-in, native session validation, logout and playback
behave as they do in the stock app.

`build_patch.py` accepts only the pinned original bundle. `standalone-shim.js`
contains the scoped runtime wrappers. The builder writes `payload/ui_patch.h`, the
insertions the payload applies on the console, and a manifest recording the exact
edits and hashes. It also writes a local `spotifytv.standalone.js` for tests; that
file contains Spotify's code and is not committed. Source SHA-256:
`bccd77047ca9bcda924c1de15f0d9990ce9eb420a5ea0733f5f75f27a47d5ebb`.
Output SHA-256:
`a1657746d0b5d6df072fe95ee34d20fa6db9665578bc746eefc1d1aad05b52b4`.

Standalone sessions require a matching current bridge session, validated Spotify
profile and native token getter. Stale events and mismatched identities are rejected.
Original SDK errors and logout behavior remain intact. Sony linking calls are
guarded only in standalone mode; normal-mode methods retain receivers and arguments.

`test_builder.py`, `test_patch.js` and `browser_tests.py` verify deterministic edits,
identity checks, stale sessions, native errors, logout, normal mode, linking guards
and deeplinks. Run the complete suite using [development instructions](../../docs/DEVELOPMENT.md).
Users do not upload any of these files; the payload patches the console's cache.
