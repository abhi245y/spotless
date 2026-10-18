# Prepare a Spotify package

Spotless does not include or download Spotify. Use your own package. The tested
version is **Spotify 01.017.000** (PPSA05688), which requires firmware 12.00 or
later. Other versions have not been tested; a package that installs is not
necessarily one Spotless can patch.

## Download

Download PPSA05688 version 01.017.000 from PROSPEROPatches or another source.
Put every file for that version in one new folder, keep the original filenames and
do not mix versions:

```text
spotify-01.017.000/
├── EP4950-PPSA05688_00-SPOTIFYMUSIC0000.pkg
├── EP4950-PPSA05688_00-SPOTIFYMUSIC0000_sc.pkg
└── EP4950-PPSA05688_00-SPOTIFYMUSIC0000.crc
```

The main piece, SC piece and CRC file are required. If the download also includes
`EP4950-PPSA05688_00-SPOTIFYMUSIC0000-DP.pkg`, leave it in the folder; the merger
ignores it because it is not covered by the CRC file.

## Merge

Requires Python 3.9 or later, with no extra packages.

```sh
python3 tools/merge_pkg.py ./spotify-01.017.000 \
  --output ./Spotify-01.017.000-MERGED.pkg \
  --expect-version 01.017.000
```

Write the output outside the input folder. The merger checks the package headers,
SC offset, title and content ID, version, and every 64 KiB block against the CRC
file. It writes to a temporary file and only publishes the result once everything
matches. It never overwrites an existing file.

The output is the two pieces joined byte for byte. Nothing is patched, signed or
decrypted. A `.pkg.json` report next to it lists the version, required firmware,
sizes and SHA-256 hashes. Note that a CRC match confirms the files are consistent
with each other, not that they are authentic.

Install the merged PKG with your usual package installer, then continue with the
[installation guide](../INSTALL.md).

## Merge errors

| Error | Fix |
| --- | --- |
| Missing input | Download every listed file and keep the original names. |
| Extra PKGs | Use a separate folder per version and move old merged outputs out. |
| CRC mismatch | Redownload the affected files. Do not bypass the check. |
| Offset, layout or metadata error | Inputs are incomplete or the layout is unsupported. Open an issue with filenames, sizes and the error. Do not join the files by hand. |
| Output exists | Choose a different output path. |
