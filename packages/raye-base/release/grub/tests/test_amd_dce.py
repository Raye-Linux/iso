"""raye-amd-dce: an AMD card with the older display engine (DCE, up to RX 500
and Vega) is the only one level 1 of the graphics ladder may give
amdgpu.dc=0; every newer card has no display without DC (RX 5700 XT black
for good, 2026-11-20)."""
import re
import subprocess
from pathlib import Path

GRUB = Path(__file__).resolve().parents[1]
DCE = GRUB / "raye-amd-dce"
EDITENV = """#!/bin/sh
f=$1; shift
case $1 in
list) cat "$f" ;;
set) shift; for kv; do k=${kv%%=*}; grep -v "^$k=" "$f" > "$f.new" || true; echo "$kv" >> "$f.new"; mv "$f.new" "$f"; done ;;
unset) shift; for k; do grep -v "^$k=" "$f" > "$f.new" || true; mv "$f.new" "$f"; done ;;
*) exit 2 ;;
esac
echo "$@" >> "$f.calls"
"""


def pc(tmp, cards, env_text="# GRUB Environment Block\n"):
    for i, (vendor, cls, device) in enumerate(cards):
        dev = tmp / "sys" / "bus" / "pci" / "devices" / f"0000:0{i}:00.0"
        dev.mkdir(parents=True)
        (dev / "vendor").write_text(vendor + "\n")
        (dev / "class").write_text(cls + "\n")
        (dev / "device").write_text(device + "\n")
    (tmp / "sys" / "bus" / "pci" / "devices").mkdir(parents=True, exist_ok=True)
    bin_ = tmp / "bin"
    bin_.mkdir()
    (bin_ / "grub-editenv").write_text(EDITENV)
    (bin_ / "grub-editenv").chmod(0o755)
    grubenv = tmp / "grubenv"
    grubenv.write_text(env_text)
    return {"PATH": f"{bin_}:/usr/bin:/bin", "RAYE_SYS": str(tmp / "sys"), "RAYE_GRUBENV": str(grubenv)}


def run(env, *args):
    return subprocess.run(["sh", str(DCE), *args], env=env, capture_output=True, text=True)


def flag(tmp):
    m = re.search(r"^raye_gfx_amd_dce=(.*)$", (tmp / "grubenv").read_text(), re.M)
    return m.group(1) if m else None


def test_rx_550_is_dce(tmp_path):
    assert run(pc(tmp_path, [("0x1002", "0x030000", "0x699f")])).returncode == 0


def test_upper_case_ids_and_vega_64(tmp_path):
    assert run(pc(tmp_path, [("0x1002", "0x030000", "0x687F")])).returncode == 0


def test_rx_5700_xt_is_not(tmp_path):
    assert run(pc(tmp_path, [("0x1002", "0x030000", "0x731f")])).returncode == 1


def test_fiji_is_dce_but_navi_with_the_same_first_digits_is_not(tmp_path):
    assert run(pc(tmp_path, [("0x1002", "0x030000", "0x7300")])).returncode == 0
    assert run(pc(tmp_path / "b", [("0x1002", "0x030000", "0x7310")])).returncode == 1


def test_ryzen_and_rdna3_not(tmp_path):
    for i, d in enumerate(["0x15dd", "0x1638", "0x744c", "0x164e"]):
        assert run(pc(tmp_path / str(i), [("0x1002", "0x030000", d)])).returncode == 1, d


def test_no_amd_card_and_amd_audio_are_not(tmp_path):
    env = pc(tmp_path, [("0x10de", "0x030000", "0x699f"), ("0x1002", "0x040300", "0x699f")])
    assert run(env).returncode == 1


def test_a_part_of_an_id_does_not_match(tmp_path):
    # 0x699 is no card; only whole ids count
    assert run(pc(tmp_path, [("0x1002", "0x030000", "0x699")])).returncode == 1


def test_every_id_is_four_hex_digits_and_the_table_is_amdgpus_older_chips():
    text = DCE.read_text()
    table = text.split('DCE_IDS="', 1)[1].split('"', 1)[0]
    rows = dict(l.split(":", 1) for l in table.strip().splitlines())
    ids = " ".join(rows.values()).split()
    assert all(re.fullmatch(r"[0-9a-f]{4}", i) for i in ids)
    assert "699f" in ids and "731f" not in ids and "7310" not in ids
    assert set(rows) >= {"polaris10", "polaris11", "polaris12", "vega10", "vega20", "tonga", "fiji"}
    assert not set(rows) & {"raven", "navi10", "renoir"}


def test_sync_writes_the_flag_once(tmp_path):
    env = pc(tmp_path, [("0x1002", "0x030000", "0x67df")])
    run(env, "--sync")
    assert flag(tmp_path) == "1"
    run(env, "--sync")
    writes = [c for c in (tmp_path / "grubenv.calls").read_text().splitlines() if c != "list"]
    assert writes == ["raye_gfx_amd_dce=1"]                # no second write


def test_sync_removes_the_flag_after_a_card_swap(tmp_path):
    env = pc(tmp_path, [("0x1002", "0x030000", "0x731f")],
             "# GRUB Environment Block\nraye_gfx_amd_dce=1\nraye_gfx_level=1\n")
    run(env, "--sync")
    assert flag(tmp_path) is None
    assert "raye_gfx_level=1" in (tmp_path / "grubenv").read_text()


def test_sync_without_grubenv_does_nothing(tmp_path):
    env = pc(tmp_path, [("0x1002", "0x030000", "0x67df")])
    (tmp_path / "grubenv").unlink()
    assert run(env, "--sync").returncode == 0
    assert not (tmp_path / "grubenv").exists()


def test_the_boot_menu_check_runs_it_at_every_start():
    ok = (GRUB / "raye-graphics-ok").read_text()
    assert "raye-amd-dce}" in ok and "--sync" in ok
    # before the wait for a session: a start that stays black syncs too
    assert ok.index("--sync") < ok.index('while [ "$i"')


def test_the_postinst_and_the_package_carry_it():
    deb = GRUB.parents[1] / "debian"
    assert "/usr/libexec/raye-amd-dce --sync || true" in (deb / "raye-system.postinst").read_text()
    assert "release/grub/raye-amd-dce" in (deb / "raye-release-paths").read_text()


def test_newer_answers_the_other_way(tmp_path):
    assert run(pc(tmp_path, [("0x1002", "0x030000", "0x731f")]), "--newer").returncode == 0
    assert run(pc(tmp_path / "b", [("0x1002", "0x030000", "0x699f")]), "--newer").returncode == 1
    assert run(pc(tmp_path / "c", [("0x10de", "0x030000", "0x2684")]), "--newer").returncode == 1
    both = pc(tmp_path / "d", [("0x1002", "0x030000", "0x699f"), ("0x1002", "0x038000", "0x1638")])
    assert run(both, "--newer").returncode == 0 and run(both).returncode == 0
