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

    def run(self):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "RAYE_GRUBENV": str(self.env_file),
               "RAYE_GFX_RETRY_MARK": str(self.mark), "RAYE_GRUB_DEFAULTS": str(self.defaults),
               "RAYE_AMD_CURSOR": str(self.bin / "amd-cursor"),
               "grub_probe": str(self.bin / "grub-probe"), "RAYE_BOOT_DIR": str(self.tmp)}
        return subprocess.run(["sh", str(RETRY)], env=env, capture_output=True, text=True)

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
