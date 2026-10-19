# ⚒ NIXFORGE tests — forged by Swanix 🐸
import pytest

from forge import safety
from forge.core import render, safe_eval


def test_render_keeps_types():
    ctx = {"watch": {"changed": True}, "x": "hi"}
    assert render("{{ watch.changed }}", ctx) is True
    assert render("say {{ x }}", ctx) == "say hi"


def test_dot_access_in_tests():
    assert safe_eval("watch.changed in [True, False]", {"watch": {"changed": False}})


def test_heal_cannot_add_messages():
    old = {"steps": [{"id": "a", "use": "fetch", "with": {"url": "u"}}]}
    new = {"steps": [{"id": "a", "use": "fetch", "with": {"url": "u"}},
                     {"id": "b", "use": "telegram", "with": {"text": "hi"}}]}
    with pytest.raises(safety.SafetyError):
        safety.check_heal(old, new)


def test_banned_code():
    with pytest.raises(safety.SafetyError):
        safety.check_code("import subprocess")


def test_secret_scan():
    with pytest.raises(safety.SafetyError):
        safety.check_spec({"steps": [{"id": "a", "use": "llm", "with": {"prompt": "gsk_" + "a" * 30}}]})
