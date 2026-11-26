# SPDX-License-Identifier: GPL-3.0-or-later
"""The notices and screens raye-base writes itself speak Spanish, German,
Brazilian Portuguese and Italian too (keys "es", "de", "pt", "it": the
language part of LANG, so pt_PT reads Brazil's words).

Every table has every English key, the same {placeholders}, and no
sentence left in English; and the script picks the language from LANG.
"""
import importlib.machinery
import importlib.util
import json
import re
from pathlib import Path

import pytest

TOP = Path(__file__).resolve().parent.parent
NEW = ("es", "de", "pt", "it")
TABLES = [("release/notices/raye-notices", "WORDS"), ("release/notices/raye-restart-notice", "WORDS"),
          ("release/notices/raye-restart-notice", "REASONS"), ("release/sleep/raye-sleep-guard", "WORDS"),
          ("release/lightmode/raye-light-mode", "WORDS"), ("release/print/raye-pdf-save", "WORDS"),
          ("release/recovery/raye-earlier-states", "WORDS"), ("release/recovery/raye-earlier-states", "TITLES")]


def load(path):
    loader = importlib.machinery.SourceFileLoader(re.sub(r"\W", "_", path), str(TOP / path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def sentence(text):
    return len(re.findall(r"[A-Za-z]{2,}", re.sub(r"\{\w+\}", "", text))) >= 3


def check(en, other, where):
    if isinstance(en, str):
        assert other, where
        assert sorted(re.findall(r"\{\w+\}", other)) == sorted(re.findall(r"\{\w+\}", en)), where
        if sentence(en):
            assert other != en, f"{where} left in English"
        return
    assert sorted(other) == sorted(en), f"{where}: keys differ"
    for key in en:
        check(en[key], other[key], f"{where}.{key}")


@pytest.mark.parametrize("path,name", TABLES)
def test_tables(path, name):
    module = load(path)
    table = getattr(module, name, None)
    if table is None:
        pytest.skip(f"{path} has no {name}")
    for lang in NEW:
        assert lang in table, f"{path}: {name} has no {lang}"
        check(table["en"], table[lang], f"{path} {name}[{lang}]")


@pytest.mark.parametrize("path", ["release/notices/raye-notices", "release/notices/raye-restart-notice",
                                  "release/sleep/raye-sleep-guard", "release/lightmode/raye-light-mode",
                                  "release/print/raye-pdf-save"])
def test_language_from_lang(path):
    module = load(path)
    for env, want in (({"LANG": "es_MX.UTF-8"}, "es"), ({"LANG": "de_AT.UTF-8"}, "de"),
                      ({"LANG": "pt_BR.UTF-8"}, "pt"), ({"LANG": "it_IT.UTF-8"}, "it"),
                      ({"LANG": "nl_NL.UTF-8"}, "en")):
        assert module.language(env) == want, (path, env)


@pytest.mark.parametrize("lang", NEW)
def test_crash_words(lang):
    en = json.loads((TOP / "release/crash/locale/en.json").read_text(encoding="utf-8"))
    other = json.loads((TOP / f"release/crash/locale/{lang}.json").read_text(encoding="utf-8"))
    assert list(other) == list(en)


def test_print_queue_name():
    script = (TOP / "release/print/raye-print-to-pdf").read_text(encoding="utf-8")
    for lang in NEW:
        assert re.search(rf"^\s+{lang}\*\) name=", script, re.M), lang
