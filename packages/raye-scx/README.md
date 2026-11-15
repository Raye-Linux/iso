# raye-scx

Two CPU schedulers written in BPF, from
[sched-ext/scx](https://github.com/sched-ext/scx), built for Raye:

| Scheduler | What for | Installed to |
|---|---|---|
| `scx_lavd` | steady frame times in games: it keeps the 1 % lows up when the game competes with a download, a browser or shader compilation | `/usr/bin/scx_lavd` |
| `scx_bpfland` | a responsive desktop under load (the second candidate) | `/usr/bin/scx_bpfland` |

The kernel loads a sched_ext scheduler at run time and goes back to its
own scheduler by itself if the BPF program stalls or its process exits,
so nothing here can leave the computer without a scheduler. Ubuntu's
kernel and the Raye kernel both have `CONFIG_SCHED_CLASS_EXT=y`.

Nothing starts them on its own and there is no loader daemon. Game mode
(raye-gaming, `release/gaming/` in raye-base) starts
`raye-game-scheduler.service` while a game runs and stops it when the
game ends. Which of the two it runs, and with which flags, is decided by
the scheduler measurements (KP-13 in the kernel design notes).

## Files

- `scx.sha256`: the upstream release tarball and the vendored crates
  tarball, with the SHA-256 each must have. The version comes from it.
- `fetch-scx.sh`: downloads the release, makes the crates tarball with
  `cargo vendor`, checks both, writes the orig tarball, and unpacks
  everything at build time (`--help` lists the modes).
- `patches/`: applied by `fetch-scx.sh` to the release. `0001` cuts the
  workspace down to the two schedulers and drops from `Cargo.lock` what
  they do not need (versions unchanged), so the crates tarball is
  about 14 MB instead of hundreds.
- `tests/test_fetch_scx.py`: tests of the script, run by the build.

## Building

    ./fetch-scx.sh                    # into upstream/, then ../raye-scx_<v>.orig.tar.xz
    dpkg-buildpackage -b -us -uc      # checks upstream/ again, never downloads

`fetch-scx.sh` needs the network and `cargo` once; the build needs
neither (cargo runs with `--frozen` on the vendored crates).
`--cache DIR` keeps a copy of both archives in DIR and takes them from
there next time. `RAYE_SCX_MIRROR=https://host/path` takes both files
from one mirror; the hashes still decide. `upstream/` is not committed.

libbpf is linked in statically from the copy the `libbpf-sys` crate
carries (1.7.0): the `libbpf-rs` version upstream pins binds that API,
newer than the archive's `libbpf-dev`. libelf and zlib come from the
system.

## Moving to a new release

1. Pick a tag that says it works on the kernel Raye ships (its release
   notes and `scheds/include` gate newer kernel features by version).
2. Put its tarball's SHA-256 in `scx.sha256` (`scx-<v>.tar.gz`), and
   `debian/changelog` at `<v>-1`.
3. Remake `patches/0001`: in the new release set the workspace members
   to the two schedulers, run `cargo metadata --offline` (or online) to
   prune `Cargo.lock`, and check that no version moved.
4. Run `./fetch-scx.sh`: it stops with the crates tarball's SHA-256;
   check what changed, put it in `scx.sha256`, run it again.

## Checking on a computer

    sudo scx_lavd                        # Ctrl-C to stop
    cat /sys/kernel/sched_ext/state      # enabled while it runs
    cat /sys/kernel/sched_ext/root/ops   # lavd

With Secure Boot on the kernel runs in lockdown (integrity); loading the
scheduler is allowed there, and this is checked on both kernels before
each release.
