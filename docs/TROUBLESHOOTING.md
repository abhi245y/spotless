# Troubleshooting

## Network or PSN errors

Errors like `WV-109144-9` or `NW-102261-2` have several possible causes. Check
internet access and DNS first: a fresh install has to download its frontend before
Spotless can patch it, and loading the payload again will not help without a
connection. Do not update firmware or sign in to PSN to fix these.

If the frontend loads behind an error overlay, Spotless can still proceed. An error
page on its own is not enough.

## No success notification

- Make sure you loaded `Spotless.elf` (not the restore payload) and Spotify is open.
- Spotless waits up to ten minutes for the supported frontend to load, then exits.
  Its process disappearing does not mean the patch was removed.
- If Spotify has a different frontend version, Spotless refuses to patch it.
  Do not disable the hash checks; [open an issue](#report-an-issue) instead.

Check `/data/spotless/watcher.log` for details.

## Spotify still shows the old UI

Close Spotify fully and reopen it after the first install; the running instance
had already loaded the original frontend. If an uninstall, cache clear or Spotify
update removed the patch, load Spotless again. See
[Persistence](../INSTALL.md#persistence).

## Music sources shows "Link"

**Music > Music sources > Spotify** still opens Sony's account-linking flow. This
is a known limitation. Spotify itself is signed in and works normally.

## Wrong account signed in

Spotless never supplies credentials. Spotify may have kept an earlier session, or
your phone may have connected through Spotify Connect. Use Spotify's own logout to
switch accounts.

A clean reinstall removes local app data, but it cannot sign out your phone or
revoke sessions on Spotify's servers.

## Restore fails

Stop and keep `/data/spotless/` as it is. Restore checks the backups, the recorded
cache path and this console's cache salt, so backups from another console, or from
before a Spotify reinstall, will not work. Never upload a backup over a live cache
file. Save the log and open an issue. If you no longer need the backups, use a
clean reinstall.

## Clean reinstall

> [!WARNING]
> This uninstalls Spotify and deletes its local session, cache, per-title data and
> Spotless backups. You will need to reinstall and sign in again. Other apps,
> downloaded PKGs, network settings and shared system components are not touched.

**Requirements:** Python 3.9 or later and FTP on the console. The uninstall step
also needs a configured [PS5Upload](https://github.com/phantomptr/ps5upload)
engine and helper supporting the 6.6.1 management API. The preview works without it.

1. Close Spotify completely, including background playback, and make sure
   Spotless is not running. Enable FTP and the PS5Upload helper.
2. Run, replacing the IP with your console's:

   ```sh
   python3 tools/cleanup_console.py --host 192.168.1.2
   ```

   The script reads the console over FTP and prints what it will remove.
3. Review the list and answer the prompt:

   ```text
   Continue with uninstall and data removal on 192.168.1.2 (PPSA05688)? [y/N]:
   ```

   `y` continues. Enter, `n` or Ctrl+C cancels with no changes. Use `--dry-run`
   to print the preview and exit without asking.
4. The script confirms Spotify and Spotless are closed, uninstalls Spotify through
   the management helper, verifies it is gone, then deletes the leftover data over
   FTP. It stops at the first error and does not roll back completed steps.
5. Reinstall Spotify and follow the [installation guide](../INSTALL.md).

Options:

| Flag | Default |
| --- | --- |
| `--ftp-port` | `2121` |
| `--management-port` | `9111` |
| `--engine-url` | `http://127.0.0.1:19113` |
| `--ftp-user NAME --ask-ftp-password` | Anonymous FTP. `SPOTLESS_FTP_PASSWORD` also works. |

<details>
<summary>What gets removed</summary>

The title's installation, metadata and download/cache container, known title data
folders, per-user `savedata_prospero/PPSA05688` folders, Spotify's user
download/data folders and known files in `/data/spotless/`. Unknown files and
downloaded packages are kept. Shared system code and savedata databases are not
edited. Unrecognised FTP listings, symlinks or incomplete process lists stop the
cleanup. Empty project folders may remain.

</details>

### Cleanup errors

- **`Connection refused` for `http://127.0.0.1:19113`:** the PS5Upload engine is
  not running on your computer. `--host` sets the console address, not the engine.
  Start the engine and connect its console helper, or pass
  `--engine-url http://HOST:PORT`. Nothing is deleted when this check fails.
- **Uninstall refused or title already absent:** the script stops before deleting
  anything else. Reinstall and retry, or remove the remaining paths manually.
- **FTP errors:** check the address, port and credentials. A permission error does
  not mean a path is absent.

## Report an issue

[Open an issue](https://github.com/abhi245y/spotless/issues/new?template=bug_report.md)
with your firmware, Spotify version, loader, steps to reproduce, the exact
notification or error, and the relevant lines from `/data/spotless/watcher.log`.
For merger problems include filenames, sizes and the error. For cleanup problems
say which step failed and whether the uninstall completed.

Never attach tokens, passwords, raw cache records, backup files or PKGs.
