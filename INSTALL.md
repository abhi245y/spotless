# Installation

## Before you start

- A jailbroken PS5 with an ELF loader or Payload Manager running. Set up the
  payloads and patches your firmware's jailbreak needs first.
- Spotify **01.017.000** (PPSA05688) installed. See [Prepare a package](docs/PACKAGES.md).
- Internet access, so Spotify can download its frontend on first launch.
- A Spotify account.

Tested on firmware 13.00. Spotless never installs firmware, signs in to PSN or
modifies the Spotify package.

## 1. Download

Download `Spotless.elf`, `Spotless-Restore.elf` and their `.sha256` files from
[Releases](https://github.com/abhi245y/spotless/releases), or
[build them](docs/DEVELOPMENT.md). Verify the downloads:

```sh
sha256sum -c Spotless.elf.sha256
sha256sum -c Spotless-Restore.elf.sha256
```

`Spotless.meta.json` is optional metadata (name, version, checksum) for loaders
that support it.

## 2. Apply the patch

1. Load `Spotless.elf`. You can do this before or after opening Spotify. You
   should see:

   > Spotless: Ready. Open Spotify and leave its login page open.

2. Open Spotify and leave it on the login screen. Spotless waits for the frontend
   to finish loading, verifies it, and needs five seconds of stable readiness
   before writing anything. This can take up to ten minutes on a fresh install.
3. Keep Spotify open until you see:

   > Spotless: UI patch installed. Fully close and reopen Spotify once.

4. Close Spotify fully and open it again.
5. Sign in with the on-screen code or connect from the Spotify app on your phone.

Spotless exits on its own when it finishes.

## Persistence

You only need to do this once. The patch is stored in Spotify's cache and survives
app restarts and reboots, with or without the jailbreak active.

It is lost if Spotify is uninstalled, its cache is cleared, or Spotify ships a new
frontend. Load Spotless again from a jailbroken session to reapply it. Running it
on an already patched cache is harmless: it reports the patch as installed and
changes nothing.

## Restore the original app

1. Open Spotify.
2. Load `Spotless-Restore.elf` and wait for the success notification.
3. Close Spotify fully and reopen it.

Restoring does not sign you out of Spotify.

Backups and the log live in `/data/spotless/` (`original.record`,
`patched.record`, `record-path`, `watcher.log`). Keep this folder if you may want
to restore later, and never copy files over Spotify's live cache by FTP.

## Problems

See [Troubleshooting](docs/TROUBLESHOOTING.md). To start completely fresh, use the
[clean reinstall](docs/TROUBLESHOOTING.md#clean-reinstall) tool. It uninstalls
Spotify and deletes its data, so try restoring first if you only want the original
UI back.
