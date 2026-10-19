# ─────────────────────────────────────────────────────────────
#  ⚒  NIXFORGE · planner.py — plain words in, workflow out
#  forged by Swanix 🐸
# ─────────────────────────────────────────────────────────────
"""Compile a request like "ping me when the GATE notice page changes" into
workflows/<slug>/spec.yaml with status: pending, dry-run it, then ask the
owner on Telegram to approve. Nothing runs on a schedule until approved.

  python -m forge.planner "<request in plain words>"
"""
import json
import os
import re
import sys

import requests
import yaml

from . import safety
from .blocks import catalog
from .core import StepError, save_spec, wf_path
from .llm import chat_json
from .runner import execute
from .sig import SIGN_OFF, banner, log

SYSTEM = """You are the NIXFORGE planner, built by Swanix. Turn the user's request
into a workflow spec using ONLY the listed blocks. Rules:
- steps run top to bottom; reference earlier outputs as "{{ step_id }}" or
  "{{ step_id.field }}"; use "when": "{{ step.changed }}" for conditions.
- schedule is a 5-field cron in the given tz (Asia/Kolkata). Never more often
  than every 15 minutes. Omit schedule for on-demand workflows.
- telegram only ever messages the owner. There is NO way to spend money,
  post publicly, message other people or delete data: if asked, set
  "unsupported" to the reason and "unsupported_kind" to "forbidden".
- if it's allowed but no block can do it yet, set "unsupported" and
  "unsupported_kind": "missing" (NIXFORGE will pitch an evolution).
- add 1-3 "tests": python expressions over step outputs proving it worked
  (e.g. "len(headline) > 0").
- if a website change watcher: fetch → select → diff → telegram when changed.
"""

EXAMPLE = {
    "id": "gate_notice_watch", "title": "Watch the GATE notices page", "schedule": "*/30 * * * *",
    "tz": "Asia/Kolkata", "status": "pending",
    "steps": [
        {"id": "page", "use": "fetch", "with": {"url": "https://example.com/notices"}},
        {"id": "latest", "use": "select", "with": {"html": "{{ page }}", "css": "ul.notices li"}},
        {"id": "watch", "use": "diff", "with": {"key": "latest", "value": "{{ latest }}"}},
        {"id": "ping", "use": "telegram", "when": "{{ watch.changed }}",
         "with": {"text": "🔔 New notice: {{ latest }}"}},
    ],
    "tests": ["len(latest) > 0"],
}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "workflow"


def plan(request: str) -> tuple[str, dict]:
    ans = chat_json(
        f"BLOCKS:\n{catalog()}\n\nEXAMPLE SPEC:\n{json.dumps(EXAMPLE)}\n\nREQUEST: {request}\n\n"
        'Return {"spec": {...}, "summary": "<2 short lines a non-coder understands>", '
        '"unsupported": null, "unsupported_kind": null}',
        SYSTEM,
    )
    if ans.get("unsupported"):
        if ans.get("unsupported_kind") == "missing":
            from .core import STATE_DIR, read_json, write_json
            from .evolve import propose
            misses = read_json(STATE_DIR / "_unsupported.json", [])
            misses.append({"request": request, "why": ans["unsupported"]})
            write_json(STATE_DIR / "_unsupported.json", misses[-50:])
            propose(f"request I couldn't do yet: {request}", ans["unsupported"])
            raise safety.SafetyError(f"I can't do that yet ({ans['unsupported']}). I've pitched you an upgrade.")
        raise safety.SafetyError(f"can't do that: {ans['unsupported']}")
    spec = ans["spec"]
    spec["status"] = "pending"
    spec.setdefault("tz", "Asia/Kolkata")
    spec["request"] = request
    spec["summary"] = ans.get("summary", "")
    safety.check_spec(spec)
    slug = slugify(spec.get("id") or spec.get("title") or request)
    n, base = 2, slug
    while wf_path(slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug, spec


def ask_owner(slug: str, spec: dict, dry_note: str) -> None:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    when = f"⏰ {spec['schedule']} ({spec['tz']})" if spec.get("schedule") else "▶️ on demand"
    steps = " → ".join(s["use"] for s in spec["steps"])
    text = (f"⚒ Forged: {spec.get('title', slug)}\n{spec.get('summary', '')}\n\n{when}\n🔗 {steps}\n"
            f"🧪 {dry_note}\n\nApprove to switch it on.\n\n{SIGN_OFF}")
    kb = {"inline_keyboard": [[{"text": "✅ Approve", "callback_data": f"approve:{slug}"},
                               {"text": "🗑 Discard", "callback_data": f"discard:{slug}"}]]}
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                  data={"chat_id": chat, "text": text, "reply_markup": json.dumps(kb)}, timeout=30)


def main(argv=None) -> int:
    banner()
    request = " ".join(argv or sys.argv[1:]).strip()
    try:
        slug, spec = plan(request)
    except Exception as e:  # noqa: BLE001
        log(f"planning failed: {e}", "err")
        token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
        if token and chat:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": f"⚒ Couldn't forge that: {e}\n\n{SIGN_OFF}"}, timeout=30)
        return 0
    save_spec(slug, spec)
    try:
        execute(slug, spec, dry=True)
        note = "dry run passed"
    except StepError as e:
        # heal it before the owner ever sees it
        import datetime as dt
        from .core import REPORT_DIR, load_spec, write_json
        from .healer import heal
        log(f"fresh forge stumbled ({e}); healing before pitching it", "heal")
        write_json(REPORT_DIR / f"{slug}.json", {"wf": slug, "step": getattr(e, "step", "?"), "error": str(e),
                                                "hint": e.hint[:6000], "inputs": {},
                                                "at": dt.datetime.now(dt.timezone.utc).isoformat()})
        result = heal(slug)
        spec = load_spec(slug)
        note = "dry run passed (auto-fixed while forging)" if result == "healed" else f"dry run hit: {str(e)[:100]}"
    log(f"forged {slug}: {note}", "forge")
    ask_owner(slug, spec, note)
    print(yaml.safe_dump(spec, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
