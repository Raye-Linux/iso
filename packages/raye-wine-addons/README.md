# raye-wine-addons

The free runtime files Windows programs expect, shipped in the image so
that opening a `.exe` never downloads anything and never asks a
question:

| Runtime | Version | Installed to | What for |
|---|---|---|---|
| Wine Mono | 10.4.1 | `/usr/share/wine/mono/wine-mono-10.4.1/` | .NET programs |
| Wine Gecko | 2.47.4 (x86, x86_64) | `/usr/share/wine/gecko/wine-gecko-2.47.4-x86{,_64}/` | web pages inside programs |
| DXVK | 2.5.2 | `/usr/share/raye/windows/dxvk/{x32,x64}/` | DirectX 8 to 11 on Vulkan |
| vkd3d-proton | 2.14 | `/usr/share/raye/windows/vkd3d-proton/{x86,x64}/` | DirectX 12 on Vulkan |

Wine looks for Mono and Gecko in `/usr/share/wine` by itself (also when
it lives in `/opt/wine-stable`), but only for the exact version it was
built for. When a new Wine series comes in, `versions.txt` says which
versions it wants; ship those. DXVK and vkd3d-proton are copied into the
ready space by `raye-windows-prepare` (raye-base); each folder has a
`VERSION` file.

## Files

- `addons.sha256`: the archives and the SHA-256 each must have. This is
  the list; the versions above come from it.
- `fetch-addons.sh`: downloads, checks, makes the orig tarball, and
  unpacks into the package at build time (`--help` lists the modes).
- `versions.txt`: which Mono and Gecko each Wine version looks for.
- `tests/test_fetch_addons.py`: tests of the script, run by the build.
- `msstyles/`: the Raye theme for Windows programs (its own README).

## Building

    ./fetch-addons.sh                 # into upstream/, then ../raye-wine-addons_<v>.orig.tar.xz
    dpkg-buildpackage -b -us -uc      # checks upstream/ again, never downloads

`--cache DIR` keeps a copy of each archive in DIR and takes them from
there next time (offline builds). `RAYE_ADDONS_MIRROR=https://host/path`
takes every file from one mirror; the hashes still decide. `upstream/` is
not committed.

The orig tarball is this folder without `debian/`, with the archives in
`upstream/`. Any change outside `debian/` therefore means a new upstream
version.

## Moving to new versions

1. Download the new archives and write their SHA-256 in `addons.sha256`.
   Check each hash against a second source before trusting it: the
   GitHub release digest (Mono, recent vkd3d-proton), the hash winetricks
   pins (DXVK), the `MONO_SHA`/`GECKO_SHA` of Wine's
   `dlls/appwiz.cpl/addons.c` for the `.msi` of the same release.
2. Update `versions.txt` (the row of the Wine series Raye installs gets
   `yes`).
3. New `debian/changelog` entry: the upstream version is
   `<mono>+gecko<gecko>+dxvk<dxvk>+vkd3d<vkd3d>`;
   `fetch-addons.sh --check` refuses anything else.

The hashes of this release were checked like that: Mono against its
GitHub release digest, DXVK against winetricks 20250102 (`dxvk2052`),
Gecko and vkd3d-proton against a second published checksum.

## Licences

Mono: MIT X11, LGPL, GPL with exceptions, Ms-PL, zlib (see
`debian/copyright`). Gecko: MPL 2.0. DXVK: zlib. vkd3d-proton: LGPL 2.1
or later. Their source is linked in `debian/copyright`; whoever
publishes the binary package also publishes those source archives next
to it.
