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
