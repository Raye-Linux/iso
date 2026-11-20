"""raye-graphics-retry: once, when the AMD RGBA8888 fix is installed, a PC the
graphics ladder left in a fallback level tries the normal level again, if its
card is one the fix covers. Never twice, never over the user's own words."""
import subprocess
from pathlib import Path

GRUB = Path(__file__).resolve().parents[1]
RETRY = GRUB / "raye-graphics-retry"

EDITENV = """#!/bin/sh
f=$1; shift
case $1 in
list) cat "$f" ;;
set) shift
    for kv; do
        k=${kv%%=*}
        grep -v "^$k=" "$f" > "$f.new" || true
        echo "$kv" >> "$f.new"
        mv "$f.new" "$f"
    done ;;
*) exit 2 ;;
esac
"""


class PC:
    def __init__(self, tmp, level="2", fails="0", fs="ext4", covered=True):
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.bin.mkdir()
        self.env_file = tmp / "grubenv"
        lines = ["# GRUB Environment Block"]
        if level is not None:
            lines.append(f"raye_gfx_level={level}")
        if fails is not None:
            lines.append(f"raye_gfx_fails={fails}")
        self.env_file.write_text("\n".join(lines) + "\n")
        self.script("grub-editenv", EDITENV)
        self.script("grub-probe", f"#!/bin/sh\necho {fs}\n")
        self.script("amd-cursor", "#!/bin/sh\n[ \"$1\" = --covered ] && exit %d\nexit 2\n"
                    % (0 if covered else 1))
        self.defaults = tmp / "default"
        (self.defaults / "grub.d").mkdir(parents=True)
        (self.defaults / "grub").write_text(
            'GRUB_DEFAULT=0\nGRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\nGRUB_CMDLINE_LINUX=""\n')
        (self.defaults / "grub.d" / "50-raye.cfg").write_text((GRUB / "50-raye.cfg").read_text())
        self.mark = tmp / "state" / "gfx-retry"

    def script(self, name, text):
        p = self.bin / name
        p.write_text(text)
        p.chmod(0o755)

    def run(self, *args):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "RAYE_GRUBENV": str(self.env_file),
               "RAYE_GFX_RETRY_MARK": str(self.mark), "RAYE_GRUB_DEFAULTS": str(self.defaults),
               "RAYE_AMD_CURSOR": str(self.bin / "amd-cursor"),
               "grub_probe": str(self.bin / "grub-probe"), "RAYE_BOOT_DIR": str(self.tmp)}
        return subprocess.run(["sh", str(RETRY), *args], env=env, capture_output=True, text=True)

    def state(self):
        out = {}
        for line in self.env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                out[k] = v
        return out


def test_fallback_pc_with_an_amd_card_tries_normal_again(tmp_path):
    pc = PC(tmp_path, level="2", fails="1")
    assert pc.run().returncode == 0
    assert pc.state()["raye_gfx_level"] == "0"
    assert pc.state()["raye_gfx_fails"] == "0"
    assert pc.mark.exists()


def test_level_one_too(tmp_path):
    pc = PC(tmp_path, level="1")
    pc.run()
    assert pc.state()["raye_gfx_level"] == "0"


def test_only_once(tmp_path):
    pc = PC(tmp_path, level="2")
    pc.run()
    # the ladder steps down again after two failed starts
    pc.env_file.write_text("raye_gfx_level=1\nraye_gfx_fails=0\n")
    pc.run()
    assert pc.state()["raye_gfx_level"] == "1"


def test_a_pc_at_the_normal_level_is_left_and_never_reset_later(tmp_path):
    pc = PC(tmp_path, level="0")
    pc.run()
    assert pc.state()["raye_gfx_level"] == "0"
    assert pc.mark.exists()
    pc.env_file.write_text("raye_gfx_level=2\nraye_gfx_fails=0\n")
    pc.run()
    assert pc.state()["raye_gfx_level"] == "2"


def test_no_level_yet(tmp_path):
    pc = PC(tmp_path, level=None, fails=None)
    assert pc.run().returncode == 0
    assert "raye_gfx_level" not in pc.state()


def test_other_cards_keep_their_level(tmp_path):
    pc = PC(tmp_path, level="2", covered=False)
    pc.run()
    assert pc.state()["raye_gfx_level"] == "2"
    assert pc.mark.exists()


def test_boot_grub_cannot_write_to_is_left_alone(tmp_path):
    pc = PC(tmp_path, level="2", fs="btrfs")
    pc.run()
    assert pc.state()["raye_gfx_level"] == "2"


def test_user_nomodeset_in_etc_default_grub(tmp_path):
    pc = PC(tmp_path, level="2")
    (pc.defaults / "grub").write_text('GRUB_CMDLINE_LINUX_DEFAULT="quiet splash nomodeset"\n')
    pc.run()
    assert pc.state()["raye_gfx_level"] == "2"


def test_user_amdgpu_dc_in_grub_d(tmp_path):
    pc = PC(tmp_path, level="1")
    (pc.defaults / "grub.d" / "99-mine.cfg").write_text(
        'GRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT amdgpu.dc=0"\n')
    pc.run()
    assert pc.state()["raye_gfx_level"] == "1"


def test_words_in_comments_do_not_count(tmp_path):
    pc = PC(tmp_path, level="2")
    (pc.defaults / "grub").write_text('# GRUB_CMDLINE_LINUX="nomodeset"\nGRUB_DEFAULT=0\n')
    pc.run()
    assert pc.state()["raye_gfx_level"] == "0"


def test_no_grubenv(tmp_path):
    pc = PC(tmp_path)
    pc.env_file.unlink()
    assert pc.run().returncode == 0
    assert not pc.env_file.exists()


def test_failed_write_is_tried_again_next_time(tmp_path):
    pc = PC(tmp_path, level="2")
    pc.script("grub-editenv", EDITENV.replace("set) shift", "set) exit 1; shift"))
    pc.run()
    assert not pc.mark.exists()
    assert pc.state()["raye_gfx_level"] == "2"


def test_postinst_runs_it_after_the_safe_graphics_migration():
    postinst = (GRUB.parents[1] / "debian" / "raye-system.postinst").read_text()
    migration = postinst.index("90-raye-safe-graphics.cfg")
    call = postinst.index("/usr/libexec/raye-graphics-retry")
    assert migration < call


def test_a_word_that_only_contains_nomodeset_does_not_count(tmp_path):
    pc = PC(tmp_path, level="2")
    (pc.defaults / "grub").write_text('GRUB_CMDLINE_LINUX_DEFAULT="quiet raye.nomodeset_hint=1"\n')
    pc.run()
    assert pc.state()["raye_gfx_level"] == "0"


# --driver: a graphics driver came in or changed (raye-gpu-driver-changed)

def test_driver_change_brings_an_nvidia_pc_back_from_nomodeset(tmp_path):
    # not an AMD card: the RGBA8888 retry would leave it, a new driver must not
    pc = PC(tmp_path, level="2", fails="1", covered=False)
    assert pc.run("--driver").returncode == 0
    assert pc.state()["raye_gfx_level"] == "0"
    assert pc.state()["raye_gfx_fails"] == "0"


def test_driver_change_works_again_and_again(tmp_path):
    pc = PC(tmp_path, level="2", covered=False)
    pc.mark.parent.mkdir(parents=True)
    pc.mark.write_text("")          # the once-only AMD retry already ran
    pc.run("--driver")
    assert pc.state()["raye_gfx_level"] == "0"
    pc.env_file.write_text("raye_gfx_level=1\nraye_gfx_fails=0\n")
    pc.run("--driver")
    assert pc.state()["raye_gfx_level"] == "0"


def test_driver_change_leaves_no_mark(tmp_path):
    pc = PC(tmp_path, level="2", covered=False)
    pc.run("--driver")
    assert not pc.mark.exists()     # the AMD retry still runs once later


def test_driver_change_keeps_the_users_own_nomodeset(tmp_path):
    pc = PC(tmp_path, level="2", covered=False)
    (pc.defaults / "grub.d" / "90-raye-safe-graphics.cfg").write_text(
        'GRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT nomodeset"\n')
    pc.run("--driver")
    assert pc.state()["raye_gfx_level"] == "2"


def test_driver_change_on_a_normal_pc_changes_nothing(tmp_path):
    pc = PC(tmp_path, level="0", fails="1", covered=False)
    before = pc.env_file.read_text()
    pc.run("--driver")
    assert pc.env_file.read_text() == before


# --- --no-amd: level 1 left by the old count -------------------------------
#
# Up to 1.0 Beta, the ladder counted a start that only reached the sign-in
# screen as a black screen, and an update's own starts too. Two starts in a
# row without anyone signing in (an update restart at night, or a restart
# from the sign-in screen) put the PC on level 1: amdgpu.dc=0 and no boot
# screen, for good. Measured on VM 130 (0.5, encrypted, 2026-11-20): the
# update to 1.0 Beta 2 then ran on a text screen. On a card that is not AMD
# level 1 only takes the boot screen away, so it goes back to level 0, once.

def fake_card(pc, vendor, cls="0x030000", name="0000:00:02.0", device=None):
    dev = pc.tmp / "sys" / "bus" / "pci" / "devices" / name
    dev.mkdir(parents=True)
    (dev / "vendor").write_text(vendor + "\n")
    (dev / "class").write_text(cls + "\n")
    if device is None:
        # an AMD card is an RX 550 (Polaris 12, older display engine) unless said
        device = "0x699f" if vendor == "0x1002" else "0x1234"
    (dev / "device").write_text(device + "\n")


def run_no_amd(pc):
    env = {"PATH": f"{pc.bin}:/usr/bin:/bin", "RAYE_GRUBENV": str(pc.env_file),
           "RAYE_GFX_LEVEL1_MARK": str(pc.tmp / "state" / "level1"),
           "RAYE_GFX_RETRY_MARK": str(pc.mark), "RAYE_GRUB_DEFAULTS": str(pc.defaults),
           "RAYE_AMD_CURSOR": str(pc.bin / "amd-cursor"), "RAYE_SYS": str(pc.tmp / "sys"),
           "RAYE_AMD_DCE": str(GRUB / "raye-amd-dce"),
           "grub_probe": str(pc.bin / "grub-probe"), "RAYE_BOOT_DIR": str(pc.tmp)}
    return subprocess.run(["sh", str(RETRY), "--no-amd"], env=env, capture_output=True, text=True)


def test_level_one_without_amd_card_goes_back_to_normal(tmp_path):
    pc = PC(tmp_path, level="1", fails="2", covered=False)
    fake_card(pc, "0x1af4")                       # virtio-gpu
    assert run_no_amd(pc).returncode == 0
    assert pc.state()["raye_gfx_level"] == "0"
    assert pc.state()["raye_gfx_fails"] == "0"
    assert (tmp_path / "state" / "level1").exists()


def test_level_one_with_an_amd_card_is_kept(tmp_path):
    pc = PC(tmp_path, level="1", covered=False)
    fake_card(pc, "0x8086", name="0000:00:02.0")
    fake_card(pc, "0x1002", name="0000:03:00.0")  # an AMD card beside the Intel one
    run_no_amd(pc)
    assert pc.state()["raye_gfx_level"] == "1"


def test_an_amd_device_that_is_not_a_display_does_not_count(tmp_path):
    pc = PC(tmp_path, level="1", covered=False)
    fake_card(pc, "0x10de")
    fake_card(pc, "0x1002", cls="0x040300", name="0000:03:00.1")   # HDMI audio
    run_no_amd(pc)
    assert pc.state()["raye_gfx_level"] == "0"


def test_nomodeset_level_is_kept(tmp_path):
    # level 2 was reached through two more black starts: a real black screen
    pc = PC(tmp_path, level="2", covered=False)
    fake_card(pc, "0x10de")
    run_no_amd(pc)
    assert pc.state()["raye_gfx_level"] == "2"


def test_no_amd_runs_once(tmp_path):
    pc = PC(tmp_path, level="1", covered=False)
    fake_card(pc, "0x1af4")
    run_no_amd(pc)
    assert pc.state()["raye_gfx_level"] == "0"
    pc.env_file.write_text("raye_gfx_level=1\nraye_gfx_fails=0\n")   # the ladder stepped down again
    run_no_amd(pc)
    assert pc.state()["raye_gfx_level"] == "1"


def test_no_amd_keeps_the_users_own_words(tmp_path):
    pc = PC(tmp_path, level="1", covered=False)
    fake_card(pc, "0x1af4")
    (pc.defaults / "grub.d" / "99-mine.cfg").write_text('GRUB_CMDLINE_LINUX="$GRUB_CMDLINE_LINUX amdgpu.dc=0"\n')
    run_no_amd(pc)
    assert pc.state()["raye_gfx_level"] == "1"


def test_no_amd_does_not_use_the_amd_fix_mark(tmp_path):
    # the RGBA8888 retry ran on every PC (and left its mark) long ago
    pc = PC(tmp_path, level="1", covered=False)
    fake_card(pc, "0x1af4")
    pc.mark.parent.mkdir(parents=True)
    pc.mark.write_text("")
    run_no_amd(pc)
    assert pc.state()["raye_gfx_level"] == "0"


def test_postinst_runs_no_amd():
    text = (GRUB.parents[1] / "debian" / "raye-system.postinst").read_text()
    assert "/usr/libexec/raye-graphics-retry --no-amd || true" in text


# The update from 0.5 or 1.0 Beta: the old count took a start that only
# reached the sign-in screen (a night restart, the update's own start) for a
# black screen. --no-amd runs once, from the postinst, during the update's
# start -- when the PC may still be on level 0 with two such tries counted.
# The first start of the new system would then take level 1 (no boot screen)
# with the mark already set, so nothing would ever give the boot screen back.
# Reproduced on VM 130 (0.5, encrypted, ext4 /boot, virtio-gpu): two starts
# without anyone signing in -> raye_gfx_level=1, "plymouth.enable=0".

def test_old_tries_on_level_zero_are_forgotten(tmp_path):
    pc = PC(tmp_path, level="0", fails="2", covered=False)
    fake_card(pc, "0x1af4")
    assert run_no_amd(pc).returncode == 0
    assert pc.state()["raye_gfx_fails"] == "0"
    assert pc.state()["raye_gfx_level"] == "0"
    assert (tmp_path / "state" / "level1").exists()


def test_old_tries_without_a_level_yet_are_forgotten(tmp_path):
    pc = PC(tmp_path, level=None, fails="1", covered=False)
    fake_card(pc, "0x8086")
    run_no_amd(pc)
    assert pc.state()["raye_gfx_fails"] == "0"


def test_old_tries_are_kept_with_an_amd_card(tmp_path):
    # on an AMD card a black screen is what the ladder exists for
    pc = PC(tmp_path, level="0", fails="2", covered=False)
    fake_card(pc, "0x1002")
    run_no_amd(pc)
    assert pc.state()["raye_gfx_fails"] == "2"


def test_no_tries_nothing_is_written(tmp_path):
    pc = PC(tmp_path, level=None, fails=None, covered=False)
    fake_card(pc, "0x1af4")
    before = pc.env_file.read_text()
    run_no_amd(pc)
    assert pc.env_file.read_text() == before


# --- a newer AMD card on level 1 ---------------------------------------------
#
# Level 1 wrote amdgpu.dc=0 on every PC. Only AMD cards up to RX 500 / Vega
# (older display engine, DCE) have a display path without DC: an RX 5700 XT
# (Navi 10, 0x731f) on level 1 stayed black for 7 minutes through its first
# update, no boot screen (2026-11-20). The update brings such a PC back to
# level 0, and forgets the tries the old count left.

def test_level_one_with_a_newer_amd_card_goes_back_to_normal(tmp_path):
    pc = PC(tmp_path, level="1", fails="1", covered=False)
    fake_card(pc, "0x1002", device="0x731f")          # RX 5700 XT
    fake_card(pc, "0x1002", cls="0x040300", name="0000:03:00.1", device="0xab38")
    assert run_no_amd(pc).returncode == 0
    assert pc.state()["raye_gfx_level"] == "0"
    assert pc.state()["raye_gfx_fails"] == "0"


def test_old_tries_are_forgotten_with_a_ryzen_graphics_chip(tmp_path):
    pc = PC(tmp_path, level="0", fails="2", covered=False)
    fake_card(pc, "0x1002", cls="0x038000", device="0x1638")   # Ryzen 5000 graphics
    run_no_amd(pc)
    assert pc.state()["raye_gfx_fails"] == "0"


def test_an_older_amd_card_beside_a_newer_one_keeps_level_one(tmp_path):
    pc = PC(tmp_path, level="1", covered=False)
    fake_card(pc, "0x1002", device="0x1638")
    fake_card(pc, "0x1002", name="0000:03:00.0", device="0x67DF")   # RX 580, upper case
    run_no_amd(pc)
    assert pc.state()["raye_gfx_level"] == "1"
