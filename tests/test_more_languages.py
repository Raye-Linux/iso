# SPDX-License-Identifier: GPL-3.0-or-later
"""Spanish, German, Brazilian Portuguese and Italian come with the image.

Setup offers these four next to English and French, and an install may
have no network: their language packs, spelling dictionaries, locales and
Firefox language packs must already be in the image, the same way
tests/test_french_session.sh holds French.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIVE = (ROOT / "config/live.list").read_text(encoding="utf-8").split("\n")
CONTROL = (ROOT / "packages/raye-base/debian/control").read_text(encoding="utf-8")
BUILD = (ROOT / "build.sh").read_text(encoding="utf-8")
LANGS = {"es": ("es", "hunspell-es", "firefox-l10n-es-es", "es_ES"),
         "de": ("de", "hunspell-de-de", "firefox-l10n-de", "de_DE"),
         "pt_BR": ("pt", "hunspell-pt-br", "firefox-l10n-pt-br", "pt_BR"),
         "it": ("it", "hunspell-it", "firefox-l10n-it", "it_IT")}


def desktop_depends():
    block = CONTROL[CONTROL.index("Package: raye-desktop"):]
    block = block[:block.index("\n\n")] if "\n\n" in block else block
    lines = [li for li in block.splitlines() if not li.lstrip().startswith("#")]
    text = "\n".join(lines)
    return re.split(r"[,\s]+", text[text.index("Depends:") + len("Depends:"):])


@pytest.mark.parametrize("lang", sorted(LANGS))
def test_language_support_is_in_the_image(lang):
    pack, hunspell, firefox, locale = LANGS[lang]
    live = [li.strip() for li in LIVE if li.strip() and not li.startswith("#")]
    for name in (f"language-pack-{pack}", f"language-pack-kde-{pack}", f"language-pack-gnome-{pack}", hunspell):
        assert name in live, f"{name} is not in config/live.list"
    assert firefox in desktop_depends(), f"raye-desktop does not depend on {firefox}"
    line = next(li for li in BUILD.splitlines() if "locale-gen" in li and "in_root" in li)
    assert f"{locale}.UTF-8" in line, f"{locale} is not generated"
