# Changelog

## 0.2.0-beta

First public release.

### Added

- `Spotless.elf`: patches the console's own cached Spotify frontend with a small
  edit table. No Spotify code is shipped. Uses Spotify's normal code sign-in and
  Spotify Connect.
- Waits for verified frontend assets and backend readiness before patching.
- On-screen progress notifications and protection against duplicate runs.
- Verified backups and `Spotless-Restore.elf` to restore the original frontend.
- `tools/merge_pkg.py` for merging and verifying split Spotify packages.
- `tools/cleanup_console.py` for an opt-in clean reinstall, with a preview and
  confirmation prompt.
- Installation, package, troubleshooting and development guides.

### Tested

- Firmware 13.00 with Spotify 01.017.000 (PPSA05688).

### Known issues

- **Music > Music sources > Spotify** still shows *Link* and opens Sony's
  account-linking flow.
- Other firmware and Spotify versions are untested.
