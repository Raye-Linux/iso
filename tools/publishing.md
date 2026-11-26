# Publishing a release

Everything runs on the build machine as root. Settings are in `release.conf`
(release name, signing key, where things are staged, mirror addresses).

| Where | What |
|---|---|
| `https://dl.rayelinux.com/apt/` | apt tree on Cloudflare R2, first mirror |
| `https://dl.rayelinux.com/iso/<release>/` | ISO, SHA256SUMS(.asc), key, release notes |
| `https://raye-linux.github.io/packages/` | the same apt tree on GitHub Pages (Raye-Linux/packages) |
| `github.com/Raye-Linux/releases` | the ISO in two parts, in a release tagged `v<release>` |

Installed systems read `/etc/apt/mirrors/raye.list` (from raye-archive-keyring):
R2 first, GitHub second; apt switches by itself when one does not answer.

## Once

1. Cloudflare: an R2 bucket, its custom domain `dl.rayelinux.com`, and an
   API token with Object Read & Write on that bucket. Write
   `/var/lib/raye-release/r2.env` (root, 0600):

       R2_ACCOUNT_ID=...
       R2_ACCESS_KEY_ID=...
       R2_SECRET_ACCESS_KEY=...
       R2_BUCKET=...

2. `apt install rclone` on the build machine.
3. GitHub: public repos `Raye-Linux/packages` (empty is fine) and
   `Raye-Linux/releases` (with a README, a release needs one commit).

## Each release

    tools/publish-repo              # signed apt tree from the last image build -> /srv/publish/apt
    tools/release-files             # checksums, signature, parts -> /srv/publish/release/<release>
    tools/publish-mirrors           # R2 then GitHub Pages, the apt tree only, in one gesture

`publish-mirrors` runs `publish-r2 apt` and `publish-github apt`, tries
both even if one fails, and then fails loudly naming the mirror that did
not take the tree. The master copy is `/srv/publish/apt`, on the
host's SSD: R2 and GitHub are copies, a change made on them by hand is
overwritten. On the build machine the units in `tools/systemd/` run it by
themselves: `raye-publish-mirrors.path` when InRelease is signed again,
`raye-publish-mirrors.timer` every 30 min to catch up (a failed sync, or
a change made on the host, which virtiofs does not report here). The
last sync is in `/srv/publish/mirrors.state`.

    install -m 644 tools/systemd/raye-publish-mirrors.* /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable --now raye-publish-mirrors.path raye-publish-mirrors.timer

The tools one by one, for the ISO once it may be public:

    tools/publish-r2                # R2, apt tree only: "all" adds the ISO, which stays private for now
    tools/publish-github            # GitHub Pages, through the GitHub machine; "all" adds the ISO release

Every one of them takes `--dry-run`. Then the download page:

    cd /srv/raye/website
    python3 tools/build_pages.py --release /srv/publish/release/<release>/release.json

`/srv/publish/apt` is the published state: keep it. A package whose
version is already published must keep the same contents, or publish-repo
stops: raise the version in its `debian/changelog`. The ISO parts can be
deleted once publish-github is done.

## Folder pages

Every folder of the tree gets an `index.html` (`raye_pages.py`), written
after Release is signed: apt never reads them, a visitor browses the
tree. publish-r2 also puts a page at the top of the bucket
(`$STAGE/www/index.html`, outside `apt/`). R2 does not serve
`index.html` by itself; two Cloudflare rules on the zone rayelinux.com,
for the host dl.rayelinux.com only, do:

- URL rewrite (phase `http_request_transform`): a path ending in `/`
  is fetched as that path + `index.html`;
- redirect (phase `http_request_dynamic_redirect`): a folder path with
  no trailing `/` gets a 301 to the same with `/` -- the folders of
  `dists/` by name (`Release`, `Packages` and the by-hash files have no
  dot, so no general "no dot" rule may touch `dists/`), and under
  `pool/` any path without a dot (every pool file has one).

The rules are written by `tools/cloudflare-dl-rules` (`--apply`), which
reads `CF_API_TOKEN` from `$R2_ENV` and leaves the other rules of those
phases alone.

GitHub Pages does both by itself.

## Old versions stay downloadable for 72 hours

A version that leaves the index keeps its `.deb` in the pool for
`GRACE_HOURS` (72), out of every index: a PC that read the lists just
before a publish still finishes its download, then Raye Update reads the
lists again and takes the newest (it never installs a version its lists no
longer name). Both mirrors copy the tree as it is, so they keep these files
too, and drop them at the first publish after the 72 hours. A kept file's
time is the time it left the index. If the tree would weigh more than
`GRACE_BUDGET` (900 MB, GitHub Pages stays under 1 GB) the oldest go first.
A kept version cannot come back with other contents: raise its version.

## What may go out

The apt tree is public; the ISO is not, and never goes in it. Before a
new tree replaces the old one, publish-repo audits it
(`raye_publish.audit_tree`), and publish-github audits it again right
before the push, then the job looks once more on the GitHub machine after its copy.
Refused: an image under any name (`.iso`, `.iso.*`, or ISO 9660 content
under another name), secret key material (armored or binary OpenPGP
secret keys, a GnuPG home, `r2.env`), anything at the top that is not
`dists/`, `pool/`, `.nojekyll` or `index.html`, a non-package file in
`pool/` (an `index.html` excepted), an `index.html` that is not a folder
page (it must start with `<!DOCTYPE html>` and stay under 1 MB), a file
of 100 MB or more, a tree of 1 GB or more, and a Release that is not
signed by the shipped keyring -- InRelease must sign the very Release
that is in the tree.

    tools/publish-repo --check /srv/publish/apt

Source packages of the patched packages go in with
`--sources DIR` (a folder of `.dsc` and the files they name); they are
indexed in `dists/resolute/main/source/Sources`.

## Tests

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests

## Sources of the patched desktop

    UBUNTU_SRC="<folders with Ubuntu's .dsc>" tools/desktop-sources /var/tmp/raye/desktop-srcpkgs
    tools/publish-repo --sources /var/tmp/raye/desktop-srcpkgs

`desktop-sources` makes the source packages of plasma-workspace and
plasma-desktop as Raye ships them: Ubuntu's source, the Raye series as
quilt patches `debian/patches/raye-*`, and the Raye changelog entry of
the shipped binary. `COMPARE=source=<build tree>` refuses to write one
that does not unpack to the tree its binaries were built from.

## Raye Insider channels and the release flow

One tree, one suite per update channel. Raye Update's `raye-insider.sources` names them;
a PC reads Stable plus the suite of its channel.

| Channel | Suite | What goes there |
|---|---|---|
| Dev | `resolute-dev` | **every build, as soon as it is built**, with no VM check by us: the developers test it and report back |
| Beta | `resolute-beta` | the build with the fixes for what Dev found (promoted from Dev) |
| Public Beta | `resolute-public-beta` | the public beta, for everyone who signed up (promoted from Beta) |
| Stable | `resolute` | finished versions (promoted from Public Beta) |

The flow, for every version:

    build -> publish to resolute-dev at once -> fix -> promote to resolute-beta
          -> promote to resolute-public-beta -> promote to resolute (Stable)

    tools/publish-repo --suite resolute-dev --debs <the built .debs>        # at once
    tools/publish-repo --suite resolute-beta --from-suite resolute-dev       # the fixed build
    tools/publish-repo --suite resolute-public-beta --from-suite resolute-beta
    tools/publish-repo --suite resolute --from-suite resolute-public-beta    # Stable
    tools/publish-mirrors                                                    # after each step

`--from-suite` republishes the exact package files the channel below has now (nothing is
built again), one step up only: Dev -> Beta -> Public Beta -> Stable. Add `--dry-run` to list
them. The other suites are carried over unchanged (signed indexes and every file they name),
so publishing one channel never removes another. A fix found in Beta is a new build: it goes
to Dev first, then up again.

Which version goes where (debian/changelog): `X.Y~devN` builds go to Dev only;
`X.Y~betaN` and `X.Y~rcN` are promoted to Beta and Public Beta; `X.Y` (no `~`) is the only
pattern promoted to Stable. `~` sorts before the release, so a PC on a channel always moves
forward to the final version, and leaving a channel never downgrades (Raye Update keeps the
newer versions until Stable catches up).

A channel suite that has never been published makes `apt update` fail on the PCs that chose
it: publish-r2 and publish-github refuse a tree where one of the four suites is missing or
not signed (`raye_publish.audit_channels`), and publish-r2 reads the InRelease of all four on
dl.rayelinux.com after the upload.

## First publication of Raye Linux 1.0 (prepared, not run)

The rc3 set (`/var/tmp/raye/v1/debs-1.0-rc3`, then the 1.0 set built from it) goes to all
four suites the first time, so no channel points to a missing suite:

    D=/var/tmp/raye/v1/debs-1.0-rc3          # or the final 1.0 set
    tools/publish-repo --dry-run --debs $D                                   # read the list
    tools/publish-repo --suite resolute-dev --debs $D
    tools/publish-repo --suite resolute-beta --from-suite resolute-dev
    tools/publish-repo --suite resolute-public-beta --from-suite resolute-beta
    tools/publish-repo --suite resolute --from-suite resolute-public-beta
    tools/publish-repo --check /srv/publish/apt                              # every suite
    tools/publish-r2 apt --dry-run && tools/publish-github apt --dry-run
    tools/publish-mirrors                                                    # R2, then GitHub Pages
    for s in resolute resolute-public-beta resolute-beta resolute-dev; do
        curl -fsS -o /dev/null -w "%{http_code} $s\n" https://dl.rayelinux.com/apt/dists/$s/InRelease
        curl -fsS -o /dev/null -w "%{http_code} $s\n" https://raye-linux.github.io/packages/dists/$s/InRelease
    done
    /root/raye-final/tools/push-mirrors.py && /root/raye-final/tools/publish-git-mirror.py   # code mirrors

Only then does the website's Raye Insider page go out.
