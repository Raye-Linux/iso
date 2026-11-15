"""What the system shows says root and sudo, never administrator.

    python3 -m pytest -q debian/test_root_terms.py

Comments, tests and package names (kio-admin) keep the word.
"""
import pathlib
import re

TOP = pathlib.Path(__file__).resolve().parent.parent
OLD = re.compile(r"administrat|\badmin\b", re.I)
COMMENT = re.compile(r"^\s*(#|//|<!--)")


def shown_lines():
    for path in sorted((TOP / "release").rglob("*")):
        parts = path.relative_to(TOP).parts
        if not path.is_file() or "tests" in parts or "__pycache__" in parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if OLD.search(line) and not COMMENT.match(line):
                yield f"{path.relative_to(TOP)}:{number}: {line.strip()}"


def test_release_files_say_root():
    assert list(shown_lines()) == []


def test_package_descriptions_say_root():
    text = (TOP / "debian/control").read_text(encoding="utf-8")
    found = re.findall(r"^Description: .*(?:\n .*)*", text, re.M)
    assert found and not [d for d in found if OLD.search(d)]


def test_crash_notice_says_root_in_both_languages():
    en = (TOP / "release/crash/locale/en.json").read_text(encoding="utf-8")
    fr = (TOP / "release/crash/locale/fr.json").read_text(encoding="utf-8")
    assert "only root can read them" in en and "seul root peut les lire" in fr
