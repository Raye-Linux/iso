# SPDX-License-Identifier: GPL-3.0-or-later
"""raye-tests Image.close(): it stops at a busy mount instead of pulling
the floor out from under it.

🚨 Measured on 2026-11-06, on a real run of the launcher. The report ended
with two lines:

    raye-tests: WARNING: .../image is still mounted
    raye-tests: WARNING: .../iso is still mounted

and three separate defects stood behind them.

1. **close() carried on down the stack.** It unmounted outermost first,
   which is right, but a failure did not stop it: with the overlay still
   live it went and unmounted the squashfs underneath -- the overlay's own
   lowerdir. That leaves a tree whose floor has been taken away, and a
   loop device nothing can free, because the squashfs file it holds open
   lives on the ISO mount which is now pinned as well. One busy mount
   became three, and only two of them were reported.

2. **The work directory was removed anyway.** `shutil.rmtree(work,
   ignore_errors=True)` ran whatever happened, so it walked INTO the live
   overlay and deleted through it. Nothing of the ISO can be lost that way
   because every write lands in upperdir -- which is luck, not design. The
   same call on a read-write mount of something real would have emptied it.

3. **The warning named nothing.** By the time anyone looked, no process
   held the mount at all: a subprocess had simply not finished dying when
   close() ran, and `umount` by hand worked at the first try. A warning
   that cannot say who is holding the mount sends the reader hunting a bug
   that is already gone.

So this file builds a two-deep mount stack of its own, holds the top one
busy on purpose, and checks what close() does about it.

    python3 -I -B -m unittest discover -s tools/tests
"""

import importlib.machinery
import importlib.util
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest

TOOLS = pathlib.Path(__file__).resolve().parents[1]


def load(name):
    loader = importlib.machinery.SourceFileLoader(
        name.replace("-", "_"), str(TOOLS / name))
    module = importlib.util.module_from_spec(
        importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


rt = load("raye-tests")


def mounted(at):
    at = os.path.realpath(at)
    with open("/proc/self/mountinfo", encoding="utf-8") as fh:
        return any(line.split()[4] == at for line in fh)


@unittest.skipUnless(os.geteuid() == 0, "mounting needs root")
class ImageCloseStopsAtABusyMount(unittest.TestCase):
    """A tmpfs and an overlay ON it, as SIBLING mount points -- the exact
    shape the launcher builds (work/squash and work/image are siblings,
    and the overlay merely references the squashfs as its lowerdir).

    ⚠️ The first version of this test nested the two mounts instead, and
    it could not fail: unmounting a directory that still has a mount point
    inside it is refused by the kernel whatever close() does. The defect
    only exists because the two are siblings -- `umount .../squash`
    SUCCEEDS while the overlay above it is live, and that is what takes
    the floor away. A test whose shape differs from production proves
    something about the test.
    """

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="raye-close-test.")
        self.low = os.path.join(self.work, "low")
        self.tree = os.path.join(self.work, "image")
        up = os.path.join(self.work, "up")
        wd = os.path.join(self.work, "ovlwork")
        for d in (self.low, self.tree, up, wd):
            os.makedirs(d)
        self.assertEqual(0, subprocess.run(
            ["mount", "-t", "tmpfs", "tmpfs", self.low]).returncode)
        os.makedirs(os.path.join(self.low, "here"))
        self.assertEqual(0, subprocess.run(
            ["mount", "-t", "overlay", "overlay", "-o",
             "lowerdir=%s,upperdir=%s,workdir=%s" % (self.low, up, wd),
             self.tree]).returncode)
        # the order Image appends them in: the lower mount first
        self.image = rt.Image("(no iso)", self.work)
        self.image.mounts = [self.low, self.tree]
        self.holder = None

    def tearDown(self):
        if self.holder and self.holder.poll() is None:
            self.holder.kill()
            self.holder.wait()
        for at in (self.tree, self.low):
            for _ in range(20):
                if not mounted(at):
                    break
                if subprocess.run(["umount", at],
                                  capture_output=True).returncode == 0:
                    break
                time.sleep(0.2)
        shutil.rmtree(self.work, ignore_errors=True)

    def _hold(self, where):
        self.holder = subprocess.Popen(["sleep", "300"], cwd=where)
        for _ in range(50):
            if os.path.realpath(
                    "/proc/%d/cwd" % self.holder.pid).startswith(
                        os.path.realpath(where)):
                return
            time.sleep(0.05)
        self.fail("could not make %s busy" % where)

    def test_a_clean_stack_is_released_whole(self):
        left = self.image.close(tries=2)
        self.assertEqual(left, [])
        self.assertFalse(mounted(self.tree))
        self.assertFalse(mounted(self.low))
        self.assertEqual(self.image.mounts, [])

    def test_a_busy_inner_mount_leaves_the_outer_one_alone(self):
        """The defect, in one assertion.

        The inner mount is the one close() tries first. When it cannot be
        released, the outer one must STAY mounted -- it is the ground the
        inner one stands on.
        """
        self._hold(os.path.join(self.tree, 'here'))
        left = self.image.close(tries=2)
        self.assertTrue(mounted(self.tree), "the busy mount vanished?")
        self.assertTrue(
            mounted(self.low),
            "close() unmounted the mount UNDERNEATH a busy one -- that is "
            "exactly the cascade that pinned the ISO and its loop device")
        self.assertEqual(sorted(left), sorted([self.tree, self.low]),
                         "both have to be reported, not just the busy one")

    def test_the_holder_is_named_so_the_reader_can_act(self):
        self._hold(os.path.join(self.tree, 'here'))
        who = rt.Image.holders(self.tree)
        self.assertTrue(who, "no holder reported for a mount we are holding")
        self.assertTrue(any(str(self.holder.pid) in line for line in who),
                        "the pid holding it is not in %r" % (who,))
        self.assertTrue(any("cwd" in line for line in who),
                        "what the process holds is not said: %r" % (who,))

    def test_nothing_is_invented_when_nothing_holds_it(self):
        """⚠️ The honest answer to "who holds this?" is sometimes nobody.

        That is what the real run turned out to be, and a list of
        plausible-looking culprits would have been worse than an empty one.
        """
        self.assertEqual(rt.Image.holders(self.tree), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
