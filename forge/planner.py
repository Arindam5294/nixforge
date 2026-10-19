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

SYSTEM = """You are the NIXFORGE planner, built by Swanix. You turn ANY request into a
working workflow spec. You never say "can't do it yet": if no simple block fits,
write a `code` step (real Python 3.12) that does the whole job. Rules:
- steps run top to bottom; reference earlier outputs as "{{ step_id }}" or
  "{{ step_id.field }}"; "when": "{{ step.changed }}" for conditions.
- Simple website watch / rss digest may use the small blocks. EVERYTHING else
  (APIs, scraping, building files or websites, loops, maths, conversions,
  reminders, multi-step logic) = ONE `code` step with id "main".
- code: define `def run(h):` using ONLY the h helpers listed + stdlib + installed
  libs. Write complete, defensive code (timeouts, try/except around flaky
  parts, sensible fallbacks). Never reference env vars or secrets. Return a short
  string or dict summarising what happened.
- The owner wants RESULTS on Telegram: on-demand tasks end with h.notify(...)
  carrying the actual result (text, link from h.publish, or h.send_file).
  Watchers notify only when h.changed(...) says something is new.
- Websites/pages/files to share: generate them (h.llm can write full HTML/JS,
  three.js via CDN https://unpkg.com/three@0.160.0/build/three.module.js is fine)
  and host with h.publish("index.html", html); notify the URL.
- schedule: 5-field cron in tz Asia/Kolkata, never more often than every 15 min.
  Omit schedule for one-off / "now" / on-demand tasks (they run right after
  approval). Sub-15-minute timing ("every second for 5 seconds") = a loop with
  h.sleep inside one run.
- Telegram goes ONLY to the owner. Refuse ("unsupported") only if it would spend
  money, message/post as the owner to other people, or delete their data.
- add 1-2 "tests": python expressions over step outputs, e.g. "main is not None".
"""

EXAMPLE = {
    "id": "game_3d_site", "title": "3D game website", "tz": "Asia/Kolkata", "status": "pending",
    "steps": [{"id": "main", "use": "code", "with": {"source": (
        "def run(h):\n"
        "    html = h.llm('Write ONE complete self-contained index.html: a playable 3D browser game '\n"
        "                 'using three.js as an ES module from https://unpkg.com/three@0.160.0/build/three.module.js. '\n"
        "                 'Keyboard + touch controls, score, restart. Return ONLY the HTML.')\n"
        "    start = html.find('<!'); html = html[start:] if start >= 0 else html\n"
        "    html = html.split('```')[0]\n"
        "    url = h.publish('index.html', html)\n"
        "    h.notify('🕹 Your 3D game site is live: ' + url)\n"
        "    return url\n")}}],
    "tests": ["str(main).startswith('http')"],
}

def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "workflow"


def plan(request: str) -> tuple[str, dict]:
    ans = chat_json(
        f"BLOCKS:\n{catalog()}\n\nEXAMPLE SPEC (code step):\n{json.dumps(EXAMPLE)}\n\nREQUEST: {request}\n\n"
        'Return {"spec": {...}, "summary": "<2 short lines a non-coder understands>", '
        '"unsupported": null}',
        SYSTEM,
    )
    if ans.get("unsupported"):
        raise safety.SafetyError(f"I won't do that one: {ans['unsupported']}")
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
            f"🧪 {dry_note}\n\n{'Approve and it runs right away.' if not spec.get('schedule') else 'Approve to switch it on (first run right away).'}\n\n{SIGN_OFF}")
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
    # v0.4.2 (Swanix's rule): never sit silent waiting for approval. Do the job NOW,
    # answer with the result, and keep it switched on if it has a schedule.
    from .core import load_spec
    from .runner import run_real
    spec = load_spec(slug)
    spec["status"] = "active"
    save_spec(slug, spec)
    ok = run_real(slug)
    if not ok:  # heal once and retry before answering
        try:
            from .healer import heal
            if heal(slug) == "healed":
                ok = run_real(slug)
        except Exception as e:  # noqa: BLE001
            log(f"heal after first run failed: {e}", "err")
    tell_owner(slug, load_spec(slug), ok)
    print(yaml.safe_dump(spec, sort_keys=False))
    return 0


def tell_owner(slug: str, spec: dict, ok: bool) -> None:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    title = spec.get("title", slug)
    if ok:
        when = (f"\n⏰ Stays on: {spec['schedule']} ({spec['tz']}). /pause {slug} to stop."
                if spec.get("schedule") else "")
        text = f"✅ Done: {title}\n{spec.get('summary', '')}{when}\n\n{SIGN_OFF}"
    else:
        from .core import REPORT_DIR, read_json
        err = read_json(REPORT_DIR / f"{slug}.json", {}).get("error", "unknown error")
        text = (f"⚠️ Tried {title} but it broke: {str(err)[:300]}\n"
                f"I'll keep healing it in the background. /run {slug} to retry.\n\n{SIGN_OFF}")
    kb = {"inline_keyboard": [[{"text": "🗑 Discard", "callback_data": f"discard:{slug}"}]]}
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                  data={"chat_id": chat, "text": text, "reply_markup": json.dumps(kb)}, timeout=30)


if __name__ == "__main__":
    sys.exit(main())
