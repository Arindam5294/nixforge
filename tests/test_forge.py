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


def test_code_block_runs_and_is_quiet_in_dry_run(tmp_path, monkeypatch):
    from forge import blocks
    monkeypatch.setattr(blocks, "STATE_DIR", tmp_path)
    src = "def run(h):\n    h.notify('hi')\n    return h.publish('index.html', '<h1>x</h1>')\n"
    out = blocks.code({"_wf": "t", "_dry": True, "inputs": {}}, src)
    assert out.startswith("https://raw.githack.com/") and out.endswith("/out/t/index.html")


def test_code_block_error_carries_traceback(tmp_path, monkeypatch):
    from forge import blocks
    from forge.core import StepError
    monkeypatch.setattr(blocks, "STATE_DIR", tmp_path)
    with pytest.raises(StepError) as e:
        blocks.code({"_wf": "t", "_dry": True, "inputs": {}}, "def run(h):\n    return 1/0\n")
    assert "TRACEBACK" in e.value.hint and "SOURCE" in e.value.hint


def test_code_block_cannot_read_secrets():
    with pytest.raises(safety.SafetyError):
        safety.check_code_block("import os\ndef run(h):\n    return os.environ['GROQ_API_KEY']\n")
