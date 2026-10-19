# ─────────────────────────────────────────────────────────────
#  ⚒  NIXFORGE · evolve.py — it grows, but only with your nod
#  forged by Swanix 🐸  ·  pitch → approve → build → test → ship
# ─────────────────────────────────────────────────────────────
"""Self-evolution, gated by the owner.

Errors are healed silently (healer.py). Evolution is different: a new skill,
a better version of itself. NIXFORGE must PITCH it first (what, why, risk) and
build it only after Swanix taps Approve.

  python -m forge.evolve review          # weekly self-review → maybe a pitch
  python -m forge.evolve build <pid>     # after approval: build, test, ship

Pitches come from: requests the planner couldn't do (missing capability),
workflows broken for days, and the weekly look back over runs + heals.
Evolved blocks live in forge/blocks_ext/, are safety-checked like healed code,
must pass their own self-test, and bump VERSION + CHANGELOG.
"""
import datetime as dt
import json
import os
import sys

import requests

from .core import ROOT, STATE_DIR, read_json, write_json
from .sig import SIGN_OFF, banner, log

PROPOSALS = STATE_DIR / "_evolution.json"
EXT_DIR = ROOT / "forge" / "blocks_ext"
SYSTEM = """You are NIXFORGE's evolution architect (built by Swanix). You propose
upgrades to NIXFORGE ITSELF: new blocks (capabilities) or better versions of
existing ones. Free tiers only; no paid APIs, no cards, no phone verification.
Never propose spending money, public posting, messaging other people, deleting
data, or removing safety rules. Be concrete and brief."""


def _tg(text: str, kb: dict | None = None) -> None:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        log("no Telegram secrets; pitch saved to state only", "warn")
        return
    data = {"chat_id": chat, "text": text[:4000]}
    if kb:
        data["reply_markup"] = json.dumps(kb)
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=30)


def propose(source: str, evidence: str) -> str | None:
    """Ask the brain whether an evolution would solve this; if yes, pitch it."""
    from .blocks import catalog
    from .llm import chat_json
    book = read_json(PROPOSALS, {"next": 1, "items": {}})
    open_titles = [p["title"] for p in book["items"].values() if p["status"] == "pitched"]
    try:
        ans = chat_json(
            f"CURRENT BLOCKS:\n{catalog()}\n\nTRIGGER: {source}\nEVIDENCE:\n{evidence[:4000]}\n"
            f"ALREADY PITCHED (don't repeat): {open_titles}\n\n"
            'Return {"worth_it": true|false, "title": "...", "why": "<2 lines: the need it fills>", '
            '"what": "<what changes, in plain words>", "risk": "<1 line>", '
            '"block_name": "<snake_case new block name>", "block_doc": "<signature + one line>"}',
            SYSTEM)
    except Exception as e:  # noqa: BLE001
        log(f"evolution brain unavailable: {e}", "warn")
        return None
    if not ans.get("worth_it"):
        log("no evolution needed")
        return None
    pid = f"E{book['next']}"
    book["next"] += 1
    book["items"][pid] = {**ans, "status": "pitched", "source": source,
                          "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    write_json(PROPOSALS, book)
    _tg(f"🧬 Evolution pitch {pid}: {ans['title']}\n\n"
        f"Why: {ans['why']}\nWhat changes: {ans['what']}\nRisk: {ans['risk']}\n\n"
        f"I'll only build it if you approve.\n\n{SIGN_OFF}",
        {"inline_keyboard": [[{"text": "✅ Evolve", "callback_data": f"evolve:{pid}"},
                              {"text": "✋ Not now", "callback_data": f"shelve:{pid}"}]]})
    log(f"pitched {pid}: {ans['title']}", "forge")
    return pid


def review() -> None:
    """Weekly look back: what failed, what got healed, what was asked but impossible."""
    runs = read_json(STATE_DIR / "_runs.json", {})
    heals = read_json(STATE_DIR / "_heal.json", {})
    misses = read_json(STATE_DIR / "_unsupported.json", [])
    summary = {wf: [r for r in h[:10] if not r["ok"]] for wf, h in runs.items()}
    propose("weekly self-review", json.dumps({"recent_failures": summary, "heals": heals,
                                              "requests_i_couldnt_do": misses[-10:]})[:4000])


def build(pid: str) -> bool:
    """Owner approved: write the new block, safety-check it, self-test, ship."""
    from .llm import chat_json
    from .safety import SafetyError, check_code
    book = read_json(PROPOSALS, {"next": 1, "items": {}})
    p = book["items"].get(pid)
    if not p or p["status"] != "approved":
        log(f"{pid} is not approved; refusing to evolve", "err")
        return False
    name = p["block_name"]
    ans = chat_json(
        f"Write a NIXFORGE block module for: {p['title']}\nWhat: {p['what']}\nBlock: {p['block_doc']}\n\n"
        "Template:\nfrom forge.blocks import block, retry\n"
        f"@block('{name}', side_effect=False, doc='{p['block_doc']}')\n"
        f"def {name}(ctx, ...):\n    ...\n\ndef selftest():\n    # call the block once, assert the result; return True\n\n"
        "Only requests.get, bs4, feedparser and the stdlib (no subprocess, sockets, file deletion, posting). "
        'Return {"code": "<full python module>"}', SYSTEM)
    code = ans["code"]
    try:
        check_code(code)
    except SafetyError as e:
        log(f"evolved code refused by safety gate: {e}", "err")
        p["status"] = "failed"
        write_json(PROPOSALS, book)
        _tg(f"🧬 {pid} couldn't be built safely ({e}). Nothing changed.\n\n{SIGN_OFF}")
        return False
    EXT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXT_DIR / f"{name}.py"
    path.write_text(f"# ⚒ NIXFORGE · evolved block '{name}' ({pid}) — forged by Swanix 🐸\n{code}")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(f"forge.blocks_ext.{name}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.selftest() is not False
    except Exception as e:  # noqa: BLE001
        path.unlink(missing_ok=True)
        p["status"] = "failed"
        write_json(PROPOSALS, book)
        log(f"evolved block failed its self-test: {e}", "err")
        _tg(f"🧬 {pid} failed its self-test, so I rolled it back. Nothing changed.\n\n{SIGN_OFF}")
        return False
    ver_file = ROOT / "VERSION"
    major, minor, *_ = (ver_file.read_text().strip() if ver_file.exists() else "0.1").split(".")
    new_ver = f"{major}.{int(minor) + 1}"
    ver_file.write_text(new_ver + "\n")
    with open(ROOT / "CHANGELOG.md", "a") as f:
        f.write(f"\n## v{new_ver} · {dt.date.today()} · {pid}\n- 🧬 evolved: {p['title']} (new block `{name}`)\n"
                f"- why: {p['why']}\n- approved by Swanix 🐸\n")
    p["status"], p["version"] = "shipped", new_ver
    write_json(PROPOSALS, book)
    _tg(f"🧬 Evolved to v{new_ver}: {p['title']}. New skill `{name}` is live.\n\n{SIGN_OFF}")
    return True


def main(argv=None) -> int:
    banner()
    argv = argv or sys.argv[1:]
    if argv[:1] == ["review"]:
        review()
    elif argv[:1] == ["build"] and len(argv) > 1:
        build(argv[1])
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
