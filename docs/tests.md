# The automated tests of /srv/raye, and the one launcher that runs them

`docs/test-plan.md` is the list a person ticks on real hardware. This
file is the other half: every suite a machine can run, where it lives,
how it is started, and what it needs before its verdict means anything.

```
tools/raye-tests                     everything runnable (check is the default)
tools/raye-tests list                what exists, how it runs, what it needs
tools/raye-tests --repo iso
tools/raye-tests --suite 'iso/raye-base-*'
tools/raye-tests --iso FILE          question that image
tools/raye-tests --no-iso            repository-only verdicts
tools/raye-tests --release           also the suites gated on RAYE_RELEASE
tools/raye-tests --strict            a skipped suite fails the run too
```

The table of suites is `tools/raye_tests_suites.py`; the runner is
`tools/raye-tests`. Every entry carries a `doc` line saying **where its
command comes from** - a README line, the `add_test()` that registers
it, or the docstring of the test itself. Nothing in it is guessed, and
when a command stops matching its repository that is a bug in that file,
whose `doc` says what to go and read.

## Why it had to be written

Measured 2026-11-06, before any of this existed:

- **nothing ran these tests.** No CI anywhere
  (`find /srv/raye -path '*workflows*' -name '*.yml'` returns nothing),
  no script that chains the suites, and
  `grep -rln test_apt_sources /srv/raye` finds the file only in its own
  folder.
- **two suites had never run in the mode that proves anything.**
  `tests/test_apt_template.sh` rules on an image only when it is given
  `--iso`; `tests/test_apt_sources.sh` only when given `--root`. Run
  bare, both say so in a note and exit 0.
- `iso/tools/tests/` (publish-repo, release-files, publish-r2,
  publish-github - 24 tests) was started by nothing at all.

The first run of the launcher found **two red suites**, both of which had
been red for days without anyone being able to know.

## What one run looks like

Measured on the build machine (28 cores, Debian 13 trixie) on 2026-11-06, against
`/var/tmp/raye/isos/latest.iso`, `--jobs 4`, **55 seconds wall clock**:

| | |
|---|---|
| suites | **69** in 14 repositories |
| passing | 47 |
| failing | 2 |
| skipped, each named with its reason | 20 |
| individual tests counted | **2620** (2428 passed, 2 failed, 190 skipped inside a green suite) |

The test count is a snapshot, not a constant: `theme` went from 173 to
415 collected tests in `tests/` over the hour this was written, because
someone was adding them. The suite count is the stable number.

## The rule this launcher exists for

**A suite that cannot run is named, with its reason, and never counted as
a pass.** A test skipped in silence is worse than a test that does not
exist, because the silence is read as cover. Four silences it refuses,
each one measured here rather than imagined:

1. `python3 -m unittest discover` on a folder with no test prints
   `Ran 0 tests ... NO TESTS RAN` and **exits 0**. So a suite whose
   output can be counted must count at least one test, or it fails.
   `pytest` exits 5 for the same thing, which is also a failure here.
2. a test whose tool is missing can exit **0** after printing
   "skipped" - `files/tests/raye/test_desktop_file.sh` without
   `desktop-file-validate` - or exit **1** for want of a font - 
   `theme/tests/test_fonts.sh` without Inter. One is a false green, the
   other a false red. Both suites declare their needs in the table, so a
   missing tool makes a named skip and neither lie is possible.
3. **77** is ctest's skip code, and four tests of this tree already use
   it (`theme/tools/gallery/tests/test_shoot.sh`,
   `theme/shell/run/tests/tst_shortcut_update.sh`, and the two
   `set_tests_properties(... SKIP_RETURN_CODE 77)` that register them).
   It is honoured as a skip, with the test's own last line as the reason.
4. a suite can be green and still say, in its own output, that half of it
   did not run. `iso/purge` against an image with no archive prints
   "has no archive to install from, so the install simulation cannot
   run". That sentence is lifted into the report instead of being left in
   a log.

Two more things the report always prints: the suites that ran **but not
against the thing they are about** (`desktop/tests` without
`RAYE_DESKTOP_SRC`, `kernel/tests` without `RAYE_KERNEL_TREE`), and the
count of tests skipped **inside** a green suite - 141 of 2304 on this
machine, which is how much less the green covers than it looks like.

## It writes nothing, and proves it

Every suite runs with `PYTHONDONTWRITEBYTECODE=1`, `PYTHONPYCACHEPREFIX`
pointed outside the tree, pytest without its cache, and a work folder
under a temporary directory that is removed at the end. `check` is the
default and the only mode that runs anything.

It does not claim this, it measures it, in two ways, because the first
one has a hole:

- `git status --porcelain` of every selected repository is fingerprinted
  before and after the run. **That is not enough on its own**:
  `__pycache__/` is line 11 of `theme/.gitignore`, so bytecode dropped
  there is invisible to git. A guard that cannot see the one thing that
  goes wrong is not a guard.
- so the report also walks every selected repository afterwards and
  names every file whose mtime falls inside the run, split in two:
  bytecode and test caches, which a test run can drop, and everything
  else, which a test run never writes.

It makes no claim about **who** wrote a file. On this machine both the
launcher and the person working are root, so ownership proves nothing,
and dressing a guess as a measurement is exactly what the rest of this
tree is written to avoid.

### The leak the launcher could not close - closed 2026-11-06

`PYTHONDONTWRITEBYTECODE=1` is set for every suite, and measured to
hold: a run over `update/` and `iso/` leaves **nothing** behind. It was
not enough for a test that re-execs python, because **`-I` is isolated
mode and isolated mode ignores every `PYTHON*` variable**. Eight call
sites did it, `theme/tokens/test_tokens.py` among them, and each wrote
`__pycache__/…pyc` into the source tree whatever the launcher set - 
under `ctest` too, where there is no launcher at all.

One of those folders is **packaged**:
`installer/usr/lib/calamares/modules/`. Only `debian/rules` exporting
`PYTHONDONTWRITEBYTECODE` kept the `.pyc` out of the shipped deb, and
that export is precisely what `-I` ignores. And four `.pyc` files had
been **committed** to the installer repository since `65ec1eb`, because
its `.gitignore` never mentioned `__pycache__`.

Every call site now passes `-I -B`, the four repositories that did not
ignore `__pycache__` do, and two guards hold the line - they catch
different things, which is why both exist:

- **`raye-tests --strict` now fails** on any cache left under a
  repository. It *measures* (the tree before, the tree after), so nothing
  can hide from it. But only for a suite that **ran**: a skipped suite
  leaks nothing today and can still carry the defect.
- **`tools/tests/test_no_bytecode_leak.py`** reads the source, so it sees
  a skipped suite too. It matches the quoted argv token `"-I"`, never the
  prose, drops comment lines first - its own docstring names the flag
  four times - and excludes itself, because its two pattern lines
  *contain* the token it forbids and it flagged them on the first run.

Deliberately untouched: `#!/usr/bin/python3 -I` on the shebang of a
**shipped** script (the bench suites, `po-rename.py`, `make-apt-rank.py`).
Four tests assert those first lines byte for byte, they run once from
`/usr/bin`, and the tests that *execute* them now pass `-I -B`
themselves - which is where the leak actually was.

Before this, the report named the file and the run went green anyway.
That is how it survived: **a report that never fails is a report nobody
has to act on.**

**It never builds and never packages.** A suite that needs a compiled
tree is a named skip, so a run can never take the cores or the memory
away from an image build.

### Letting go of the image - three defects behind two warnings

A run on 2026-11-06 ended with:

    raye-tests: WARNING: .../image is still mounted
    raye-tests: WARNING: .../iso is still mounted

and the warnings were the least of it.

- **`close()` carried on down the stack.** It released outermost first,
  which is right, but a failure did not stop it: with the overlay still
  live it went and unmounted the squashfs underneath - the overlay's own
  lowerdir. That `umount` *succeeds*: `work/squash` and `work/image`
  are **siblings**, and the kernel lets the lower mount point go while
  the overlay holds only its superblock. The result is a tree whose floor
  has been taken away and a loop device nothing can free, because the
  squashfs file it holds open lives on the ISO mount that is now pinned
  too. One busy mount became three, and only two were reported. It now
  stops at the first mount it cannot release, and names the rest.
- **The work directory was removed anyway.** `shutil.rmtree(work,
  ignore_errors=True)` ran whatever happened, so it walked **into** the
  live overlay and deleted through it. Nothing of the ISO can be lost
  that way because every write lands in `upperdir` - which is luck, not
  design. The same call against a read-write mount of something real
  would have emptied it. It is now skipped when anything is still
  mounted, and the exact clean-up commands are printed instead.
- **The warning named nothing.** Measured: by the time anyone looked,
  **no process held the mount at all** - a subprocess had not finished
  dying when `close()` ran, and `umount` by hand worked at the first try.
  The retry budget went from 6 s to 18 s, and the holders are now read
  out of `/proc` (pid, what it holds, command line). When nothing holds
  it, it says that too, rather than offering a list of suspects.

`--strict` fails on a leaked mount: it is not cosmetic, it poisons the
next run's disk and leaves a loop device behind.

`tools/tests/test_image_close.py` builds the same **sibling** shape
with a tmpfs and an overlay. Its own first version nested the two mounts,
and in that shape the defect cannot occur at all - the kernel refuses to
unmount a directory that still has a mount point inside it. It passed
against the broken code. A test whose shape differs from production
proves something about the test.

## The image, and why a read-only mount is not enough

`--iso` is handed straight to `tests/test_apt_template.sh`, which mounts
the ISO itself. For the suites that want `--root` (an image *tree*) the
launcher mounts the ISO once: loop read-only, then its
`casper/filesystem.squashfs` read-only, then an **overlay** with a
throw-away upper layer on top.

The overlay is not a nicety. Measured 2026-11-06: against the bare
read-only squashfs, `tests/test_apt_sources.sh --root` cannot `mktemp`
inside the tree and reports **two FAILs** - a false red on a repository
that is right. With the overlay the same run is green and
`ok: turned on, it fetches 16 source index(es)`, which is the verdict
that was wanted. Nothing of it reaches the ISO; the upper layer is
thrown away with the work folder.

Opening an ISO needs root. Without it the image suites are skipped with
`an ISO can only be opened as root` - never silently downgraded.

## Turning named skips into runs, in one apt line

A skip is honest, but it is not a pass. Seven suites of this tree were
skipped on the build machine for want of a package, not for want of a build. On
2026-11-06 these were installed, and the seven ran:

```
apt-get install --no-install-recommends \
    qt6-declarative-dev-tools qml6-module-qttest qml-qt6 \
    qml6-module-qtquick-controls qml6-module-qtquick-effects \
    qml6-module-qtquick-layouts qml6-module-qtquick-templates \
    qml6-module-qtquick-shapes qml6-module-qtquick-dialogs \
    qml6-module-qtquick-virtualkeyboard \
    libkf6config-bin desktop-file-utils fonts-inter fonts-cascadia-code
```

| Suite | What it needed | What it did once it ran |
|---|---|---|
| `theme/qml-signin` | `qmltestrunner`, QtQuick modules | **145 pass** |
| `theme/qml-sddm` | the same | **104 pass** |
| `theme/qml-lockscreen` | the same, plus `QtQuick.Effects` | **91 pass** |
| `theme/qml-polkit` | the same, plus `-import signin` | **15 pass** |
| `theme/fonts` | Inter, Inter Display, Cascadia Mono | **1 FAIL**, below |
| `theme/tray-defaults` | `qml6` (`qml-qt6`) | 21 pass |
| `theme/run-shortcut-update` | `libkf6config-bin` | 10 pass |
| `files/desktop-file` | `desktop-file-utils` | 2 pass |

And a second apt line turned **121 tests that were skipping INSIDE
green suites** into tests that run - `plasma-integration` alone unblocked
89 of `theme/tokens`, a file that had been reporting 157 of 246:

```
apt-get install --no-install-recommends \
    plasma-integration python3-numpy librsvg2-bin \
    qml6-module-org-kde-ksvg vorbis-tools \
    xdg-user-dirs libglib2.0-bin calamares
sed -i 's/^# fr_FR.UTF-8 UTF-8/fr_FR.UTF-8 UTF-8/' /etc/locale.gen && locale-gen
```

**The locale line is the lesson, not a footnote.** With
`xdg-user-dirs` installed, `release/skel/tests` stopped skipping and
**failed**:

    ['Desktop', 'Documents', …] != ['Bureau', 'Documents', …]

which reads like Raye's first-sign-in step forgetting to localise
anything. It was not. The gate was `french_catalog()`, and it asked half
the question: the `.mo` catalogue is what the package installs, but
translating also needs the locale **compiled**, which is a separate step
no package does for you. `setlocale` fails on a locale that is not
generated and gettext falls straight back to C, in silence. The gate is
`french_missing()` now, it names whichever half is absent, and three
tests hold it to that. With `fr_FR.UTF-8` generated the suite is 18 pass,
0 skip.

A gate that checks one of the two things it needs does not merely skip
when it should run - it turns a missing machine dependency into an
accusation against the product.

The last 18 of `theme/art` were not a missing package at all. They
compare Raye's Plasma style names against **Plasma's own**, read from a
path that was hard-coded as `/usr/share/plasma/...`. Installing Debian's
`plasma-workspace` on the build machine to satisfy them would mean **203 packages
and system services** (`udisks2` among them) on the machine that drives
the lab - for the *wrong* reference, since Debian ships Plasma 6.3 and
Raye is built on Ubuntu's 6.6. The right reference was already mounted:
the test reads `RAYE_ROOT` now, `theme/art` asks for the image, and the
18 run against the Plasma those files actually sit beside. `theme/art`
went from 290 pass / 25 skip to **326 pass / 0 skip**.

**The point of the table is the one FAIL.** `theme/fonts` asserted
`kwinrc [Plugins] desktopchangeosdEnabled=false` while
`tests/config/test_kwin_plugins.py` **forbids** that very line - it was
deliberately removed from `config/kwinrc` in November 2026, because
`KPluginMetaData` already returns false when `EnabledByDefault` is
absent, so the line turned off something already off. Two tests of the
same repository contradicted each other, and only one of them ever ran.

The skip was not neutral. It was holding a red.

And three of the package names are not the ones a reader would guess:
`kreadconfig6` is in **`libkf6config-bin`**, not in `kde-cli-tools`
(which ships neither it nor `kwriteconfig6`); `qml6` is in **`qml-qt6`**,
not in `qt6-declarative-dev-tools`; and `qmltestrunner` lands in
`/usr/lib/qt6/bin`, which is **not on `PATH`** - so `command -v` says
"not installed" about a binary that is installed.

Still skipped for want of a *build*, which this launcher will not do:
`apps/*` (four), `settings/qml`, `settings/qtest`, `store/qml`,
`store/qtest`, `files/qtest`, `theme/qtest`, `theme/qml-ui`,
`theme/gallery-shoot`, `account/qml`. Plus `account/cargo` - which is
a build too, and that is why it is **not** gated on `cmd:cargo`: such a
gate would let it run the day someone installs cargo, and `cargo test`
compiles the crate. And `installer/paths-strict` (`--release`).

`installer/ui-qml` used to be on that list and did not belong there: see
the installer section below.

## The suites, repository by repository

`doc` in the table is the authority for each command; this is the map.

### account (no `.git` yet)
- **cargo** - `cargo test` with `RAYE_ACCOUNT_TEST_DB` (README).
  *Skipped: cargo is not installed on the build machine, and the integration tests
  want a throw-away PostgreSQL.*
- **qml** - `ctest` on `client/qml`. *Skipped: needs a build.*

### apps
- **sync-upstream** - `sh portal/tests/test_sync_upstream.sh <script> <work>`,
  the two positional arguments `portal/tests/CMakeLists.txt` passes.
- **cmake-version**, **cmake-po-check** - `cmake -DWORK=… -P
  cmake/tests/test_*.cmake`, as `tests/CMakeLists.txt` runs them.
- **cmake-packaging** - `cmake … -DWITH_QT=ON -P
  cmake/tests/test_packaging.cmake`. Skipped until 2026-11-06 for "it
  configures and compiles small trees of its own" - an argument of cost
  that nobody had measured. Measured: **8.0 s, 3 MB**, nothing written
  inside the repository, and it needs **no** build tree because it makes
  its own. Worse, the skip was hiding **red**: the suite failed with 12
  real failures until apps `536f68f`. Gated on `cmake`, `make`, `g++`,
  `msgunfmt`, `qmake6` and the Qt6 Test CMake package.
- **registration** - `cmake -DSRC=… -P cmake/tests/test_registration.cmake`:
  every test file is reached by a registration. Uncounted on purpose (see
  `tools/tests/test_counts_declared.py`): it prints "10 test files, all
  registered", which no counter matches.
- **portal-files**, **debian-install**, **qtest** - *skipped: they are
  handed `${CMAKE_BINARY_DIR}`, or need a compiled tree.* The qtest entry
  named three; there are **four** - `sharepicker` is registered a
  directory away in `portal/qml/tests/CMakeLists.txt`. The build also runs
  `sharesessions-bus` (the same binary under `dbus-run-session`) and ECM's
  `appstreamtest`, which **validates nothing** during `dh_auto_test`:
  it reads `install_manifest.txt`, a file `make install` writes, so it
  prints "Not installed yet, skipping" and exits 0.

### desktop
- **tests** - `pytest tests/`. Runs, but 30 of its 59 tests need
  `RAYE_DESKTOP_SRC` (a Plasma source tree) and are skipped without it.
  The report says so every time.

### files
- **catalog**, **udev-rules**, **shell-guards**, **wiring** - `sh
  tests/raye/test_*.sh` with `RAYE_FILES_SOURCE_DIR`, which is what
  `tests/raye/CMakeLists.txt` puts in the environment. Without that
  variable the scripts stop on `${RAYE_FILES_SOURCE_DIR:?}`. The last two
  are reached by that file's `file(GLOB test_*.sh)` loop, as
  `raye_test_shell_guards` (7 checks) and `raye_test_wiring` (7).
- **desktop-file** - `desktop-file-validate`, from `desktop-file-utils`.
  Left to itself this test prints "skipped" and **exits 0** - a green
  that checked nothing. The launcher gates it on the command instead.
  And its entry had **no `count=`** until 2026-11-06, while both
  siblings had one: the report printed a blank where the script says "ok:
  2 checks, 0 failed", because `counts()` returns None for an undeclared
  `how` whatever the output is. `tools/tests/test_counts_declared.py` now
  fails any suite that runs without counting and without saying why.
- **qtest** - the `test_*.cpp`. *Skipped: needs a build.*

### handbook
- **version** - `python3 -I -B tests/test_version.py`.

### installer
- **python** - `pytest -q tests debian/test_raye_paths.py`, the exact
  `add_test(python)` command.
- **paths-strict** - `RAYE_PATHS_STRICT=1 python3 debian/raye_paths.py
  check`. *Skipped unless `--release`*: `CMakeLists.txt` registers it
  only `if(RAYE_RELEASE)`, and it fails by design on every path the list
  still marks as not written yet.
- **ui-qml** - `tests/ui/run-tests.sh`: `qmltestrunner` on
  `tst_setup.qml`. **22 tests.** This was a static skip reading
  *"qmltestrunner is not installed, and the module has to be laid out by
  the build first"*. **Half of that was never true**:
  `tests/ui/stage-module.sh` lays `org.raye.setup` out exactly as the
  package installs it, with no build at all. The other half stopped being
  true the day `qmltestrunner` was installed - and nothing re-read the
  sentence. `org.raye.ui` comes from the installed `raye-style`, from the
  theme repository next door, or from `RAYE_UI_QML_DIR`.
- Note: `CMakeLists.txt` looks for `tests/test_session.sh`, which does
  not exist; the live-session check is `tests/test_session.py` and the
  **python** suite already runs it.

### iso - 24 suites
- **apt-sources** `--root <image>`, **apt-template** `--iso <file>`,
  **kernel-pin** `--root <image>`, **purge** `--root <image>`,
  **boot-menu** (`$RAYE_ROOT` and `--iso <file>`), **menu-brands**
  `--root <image>`: the six that need an image.
  (The count said 22 and the list left **kernel-pin** out until
  2026-11-06; `tools/raye-tests list | grep '^iso/' | wc -l` is the
  figure that settles it.)
- **boot-menu** was repository-only until 2026-11-06, and that is why it
  is listed above now. It reads the modules of the signed CD GRUB, and it
  read the copy installed on the machine running the tests - a different
  build from the one `build.sh:511` puts on the ISO. Measured: the
  machine's carried `all_video`, the image's did not, so `insmod
  all_video` in `grub.cfg` passed here and could never work on the disc.
  With an image the module list is a verdict; without one the suite says
  the verdict is missing rather than inventing one. It also checks the
  version in the built image (`os-release`, `lsb-release`, `issue`,
  `issue.net`, `raye.info`) and the ISO's name and volume label.
- **menu-brands** reads which applications the Start menu shows under
  someone else's brand. It does **not** demand there be none: renaming
  another project's application is not a fix, and removing a feature is
  the owner's call. It freezes the perimeter - a new foreign-brand entry
  fails, a known one disappearing is only a note, so fixing a leak never
  turns it red. Three are known as of 2026-11-06 (KDE Connect, KDE
  Connect SMS, KDE Partition Manager) out of 45 visible entries.
- **build-memoire**, **desktop-debs**: repository-only, nothing to give
  them.
- **tools** - `unittest discover -s tools/tests`. Needs `dpkg-deb`,
  `apt-ftparchive`, `apt-get`, `gpg`, `gpgv`. Four of its files are
  **cross-repository guards**: they read all of `/srv/raye` and fail here
  for a defect anywhere, which is why they live in the one repository that
  owns the launcher.
  - `test_ctest_no_tests_guard.py` - every `debian/rules` that runs ctest
    must export `CTEST_NO_TESTS_ACTION=error`, because bare `ctest` exits
    **0** on "No tests were found!!!". Its two measured blind spots are
    written in the file: `BUILD_TESTING=OFF` (ctest exits 0 with the
    variable as without; `make test`, which `dh_auto_test` runs, exits 2
    and catches it instead) and a glob that loses most of its matches
    (non-zero, so the variable cannot fire).
  - `test_test_globs_refuse_empty.py` - the second blind spot, closed.
    Every `file(GLOB)` that collects test files must stop the build when
    it matches none. It found a third hole on its first run: settings
    guards `tests/test_*.cpp` and **not** its sibling `tests/test_*.sh`,
    from which the same file registers three shell tests. Three globs are
    open (settings', files', store's) and listed in it; a new one fails.
    Its own detector is tested against fixtures, because a detector stuck
    on "guarded" made the whole file pass while printing only notes.
  - `test_counts_declared.py` - a suite may pass while counting nothing
    only if the table says why.
  - `test_no_bytecode_leak.py` - no test may re-exec python with `-I` and
    without `-B`.
- **bench** - `python3 test_raye_bench.py` in `tools/bench`.
- **raye-base-python** (`debian/rules`' own pytest line),
  **-tpm**, **-windows**, **-crash**, **-skel**,
  **-tuning-files**, **-laptop-wake**, **-vm-cursor**,
  **-start-if-needed**, **-update-grub**, **-fsck-message**,
  **-kernel-setup**.
- **scx**, **wine-addons** - the two fetch scripts' pytest suites.

### kernel
- **art** - `pytest art/`. Partial without python3-pil, fonts-inter and
  `../theme`; it skips those tests itself, and the report names it.
- **tests** - `pytest tests/`. Needs `patch`; 9 of 21 tests want
  `RAYE_KERNEL_TREE` and are skipped without it.

### settings
- **version**, **storage-clean**, **reset-settings** - `sh
  tests/test_*.sh` with `SOURCE_DIR` and `LANGUAGE=en`, exactly what
  `add_test()` puts in the environment. `test_version.sh` and
  `test_storage_clean.sh` fall back to their own folder;
  `test_reset_settings.sh` stops on `${SOURCE_DIR:?}`.
- **qtest**, **qml** - *skipped: need a build.*

### store
- **extra**, **feeds**, **plasma-discover**, **version** - one suite per
  file, `python3 -I -B tests/test_<name>.py`, which is the
  `add_test(py-<name>)` command (`-B` so no `__pycache__` lands in the
  tree).
- **qtest**, **qml** - *skipped: need a build.*

### theme
- **tokens**, **tests**, **art**, **grub** - the four pytest folders.
- **taskbarsync-pins**, **style-check-names**, **style-import-upstream**
 - three standalone unittest files.
- **tray-defaults** - needs `qml6` (`qml-qt6` on Debian). Left to
  itself this test reports three **FAIL**s for a missing interpreter,
  which reads as a product defect and is not one.
- **fonts** - needs Inter, Inter Display and Cascadia Mono. It exits
  **1** when they are missing, so the launcher gates it on the families.
- **run-shortcut-update** - needs `kreadconfig6` and `kwriteconfig6`
  (`libkf6config-bin` on Debian; **not** `kde-cli-tools`, which ships
  neither). It would exit 77 itself.
- **find-qmltestrunner** - `tests/test_find_qmltestrunner.sh`: the
  resolver below, including that it really does skip with 77 when there
  is no runner anywhere.
- **qml-lockscreen**, **qml-sddm**, **qml-signin**, **qml-polkit** - 
  `qmltestrunner` on the `tst_*.qml` of `lockscreen/`, `sddm/`,
  `signin/` and `session/polkit/`. **355 tests.** They take
  `org.raye.signin` out of the repository, so they need no build.
- **gallery-shoot** - *skipped: it is handed
  `$<TARGET_FILE:raye-gallery>`, and wants Xvfb.*
- **qtest** (the `tst_*.cpp` of `shell/`, `session/polkit/`,
  `tools/gallery/`) - *skipped: needs a build.*
- **qml-ui** - *skipped: needs a build.* `tests/qml/tst_raye_ui.qml`
  loads the compiled plugin from `${CMAKE_BINARY_DIR}/qml`, which is
  exactly what the other four do not do.

#### 355 QML tests that nothing ran, and the one line that hid them

Until 2026-11-06 this table held a single entry:

    skipped("theme/qml", ..., "qmltestrunner is not installed")

a **frozen string**. No code re-evaluated it, so installing
qmltestrunner did not change the report by one character. And nothing
else ran them either: `grep -rn add_test` over the theme repository
finds `raye-ui`, `prompt`, the C++ tests and the shell scripts - and
**no registration at all** for `lockscreen/`, `sddm/` or `signin/`.
Their `run-tests.sh` was referenced by nothing but its own comment.

So 355 tests existed, were correct, and ran nowhere. Every one of them
passed the first time it was run - which is the uncomfortable part: the
defect was never in the tests.

Two things were wrong with the old reason, and both are fixed:

- **`command -v qmltestrunner` is the wrong question.** Debian puts it
  in `/usr/lib/qt6/bin`, which is not on `PATH`; Ubuntu - the base Raye
  is built on - has it on `PATH`. `tests/find-qmltestrunner.sh` looks on
  `PATH`, in the Qt 6 bin directories of both, and at what `qmake6`
  reports, and exits **77** with a reason when it finds none.
- **a skip has to be measured at every run**, not written down once.
  Each suite now decides for itself, and `--strict` fails on a skip.

The resolver takes `QMLTESTRUNNER` and `RAYE_QT_BIN_DIRS` from the
environment, and the second is not decoration: it is what makes the
"found nothing" path testable. A guard that cannot be made to fire has
never been shown to work.

### update
- **tests** - `pytest tests`; `tests/conftest.py` puts `src/` on the path.

### website
- **backend** - `unittest discover -s tests -t tests` from
  `website/backend` (README). Needs `openssl`: the mail tests start a
  real STARTTLS server with a throw-away CA.

### wine
- **tree** - `unittest discover -s tests`.

## What is not covered, and what it would take

**12 of the 81 suites cannot run on the build machine**, and the report names every
one. After the two apt lines above they are all one thing: a build. The
figures below are the full run of 2026-11-06: 81 suites in 14
repositories, 3274 tests counted, 14 skipped - the 12 here plus the 2
release gates, which are not "cannot run" but "off unless asked".

| suites | group | what is missing |
|---|---|---|
| 10 | need a compiled tree | `apps/portal-files`, `apps/qtest`, `apps/debian-install`, `files/qtest`, `settings/qml`, `settings/qtest`, `store/qml`, `store/qtest`, `theme/qtest`, `theme/qml-ui`. By policy this launcher never builds, so an image build keeps the machine |
| 1 | a build under another name | `account/cargo` - `cargo test` compiles the crate |
| 1 | nothing builds it at all | `account/qml` - account has no `debian/` and `iso/build.sh` does not build it |
| 2 | release gates, not blocked | `installer/paths-strict` and `website/release-json`, which `--release` turns on |

This table said "16 of the 77" and listed 13 under "need a compiled
tree", and three of its names were wrong by 2026-11-06:
`apps/cmake-packaging` is now a suite that runs (8.0 s, 3 MB - the skip
was an unmeasured cost argument, and it was hiding 12 real failures),
`theme/gallery-shoot` has been `theme/gallery` for a while and runs
behind an `ok:` gate, and `account/qml` was never a compiled-tree case.
`tools/raye-tests list` and the report are the figures that settle it;
nothing here is counted by hand.

**Not one of them is a missing package any more**, and that is the
whole point of the two apt lines. On 2026-11-06 the figures were 20
skipped out of 71 suites and ~2448 tests; they are now **14 of 81 and
3274 counted**, with 355 QML tests that no build and no launcher had ever run,
121 that were skipping inside green suites, and 22 in the installer that
needed neither a build nor a package - only a sentence nobody re-read.

And two of those skips used to carry a reason that had **stopped being
true**: `theme/qml` said "qmltestrunner is not installed" after it was
installed, and `installer/ui-qml` said the module needed a build when
`stage-module.sh` lays it out without one. A skip whose reason is written
down once is a claim nobody re-checks. Where a reason is a fact about the
machine it now belongs in `needs`, which is read at every run; where it
is a fact about the work (it builds), it stays in the table - because
that one will not change.


## Where the launcher lives, and why here

`/srv/raye` is not itself a git repository, so the launcher has to live
inside one of the fourteen. `iso` is the one that assembles the
distribution and already carries tooling that reaches across the others
(`tools/tests/test_publish_repo.py` reads `../update/src`). The day an
umbrella repository exists, that is a better home.
