# ─────────────────────────────────────────────────────────────
#  ⚒  NIXFORGE · healer.py — the phoenix loop
#  forged by Swanix 🐸  ·  break → diagnose → patch → test → promote
# ─────────────────────────────────────────────────────────────
"""Self-healing for a failed workflow.

  python -m forge.healer <id>

1. Read reports/<id>.json (error, failing step, page evidence, traceback).
2. Ask the free LLM chain for a diagnosis and a patched spec.
3. Safety gate: a heal may change HOW a step works, never WHAT it may do.
4. Dry-run the patch in the sandbox (no messages, no state writes) + its tests.
5. Pass → write it and print HEALED (the Action pushes heal/<id>-<n>, merges).
   Fail → feed the new error back, try again. Hard cap: 3 per incident, 10/day.
6. Out of tries → roll back to the last green version, cool down 6 h, retry.
   Never pings the owner about errors. Only evolution pitches ask him anything.
"""
import datetime as dt
import hashlib
import json
import os
import shutil
import sys

import yaml

from . import safety
from .blocks import catalog
from .core import GREEN_DIR, REPORT_DIR, STATE_DIR, StepError, load_spec, read_json, save_spec, wf_path, write_json
from .llm import chat_json
from .runner import execute
from .sig import banner, log

MAX_PER_INCIDENT = int(os.environ.get("NIXFORGE_MAX_HEAL", 3))
MAX_PER_DAY = int(os.environ.get("NIXFORGE_MAX_HEAL_DAY", 10))
HEAL = STATE_DIR / "_heal.json"

SYSTEM = """You are the NIXFORGE healer (built by Swanix). A workflow step failed.
Fix it by changing ONLY how steps work: selectors, URLs on the same site, parsing,
arguments, templates, tests that were wrong. NEVER add, remove or retarget
side-effect steps (telegram, convert), never change schedule/tz/status, never
put secrets in the spec. Prefer the smallest change that makes the tests pass.
For a `code` step: read the TRACEBACK and SOURCE, then return the step with a
corrected `with.source` (still `def run(h):`, same notify behaviour). Rewrite
freely: different URLs/APIs, parsing, fallbacks — whatever makes it work.
If the cause is outside our control (site gone, auth, quota), say fixable=false."""


def _out(**kv):
    gh_out = os.environ.get("GITHUB_OUTPUT")
    for k, v in kv.items():
        print(f"{k}={v}")
        if gh_out:
            with open(gh_out, "a") as f:
                f.write(f"{k}={v}\n")


def _notify(text: str, quiet: bool) -> None:
    from .blocks import telegram
    try:
        telegram({"_dry": False}, text, quiet=quiet)
    except Exception as e:  # noqa: BLE001
        log(f"could not notify owner: {e}", "warn")


def rollback_and_pause(wf_id: str, why: str) -> None:
    """Silent by design (Swanix's rule: fix errors yourself, don't ping me).

    Roll back to the last green version and cool down 6 h, then healing gets a
    fresh set of tries. Still broken after 3 days → pause quietly, and if the
    cause is a missing capability, file an evolution pitch (the ONE thing that
    asks the owner)."""
    green = GREEN_DIR / f"{wf_id}.yaml"
    if green.exists():
        shutil.copy(green, wf_path(wf_id))
        log(f"rolled back {wf_id} to last green version", "heal")
    state = read_json(HEAL, {})
    w = state.setdefault(wf_id, {})
    now = dt.datetime.now(dt.timezone.utc)
    w.setdefault("broken_since", now.isoformat(timespec="seconds"))
    w["cooldown_until"] = (now + dt.timedelta(hours=6)).isoformat(timespec="seconds")
    w["tries"], w["last_giveup"] = 0, why[:300]
    if now - dt.datetime.fromisoformat(w["broken_since"]) > dt.timedelta(days=3):
        spec = load_spec(wf_id)
        spec["status"] = "paused"
        save_spec(wf_id, spec)
        log(f"{wf_id} broken for 3 days; paused quietly", "heal")
        from .evolve import propose
        propose(source=f"workflow '{wf_id}' stayed broken 3 days", evidence=why)
    write_json(HEAL, state)


def heal(wf_id: str) -> str:
    report = read_json(REPORT_DIR / f"{wf_id}.json", None)
    if not report:
        log(f"no failure report for {wf_id}; nothing to heal")
        return "noop"
    state = read_json(HEAL, {})
    today = dt.date.today().isoformat()
    day = state.setdefault("_day", {"date": today, "count": 0})
    if day["date"] != today:
        state["_day"] = day = {"date": today, "count": 0}
    w = state.setdefault(wf_id, {})
    incident = hashlib.md5(f"{report['step']}|{report['error'][:80]}".encode()).hexdigest()[:8]

    # a fix that failed its first real run gets reverted, not re-healed
    if w.get("probation"):
        w["probation"] = False
        write_json(HEAL, state)
        rollback_and_pause(wf_id, f"the last auto-fix failed in a real run ({report['error'][:160]})")
        return "rolled_back"

    cool = w.get("cooldown_until")
    if cool and dt.datetime.now(dt.timezone.utc) < dt.datetime.fromisoformat(cool):
        log(f"{wf_id} cooling down until {cool}; healer rests")
        return "cooldown"
    if w.get("incident") != incident:
        w.update(incident=incident, tries=0)
    original = load_spec(wf_id)
    current = original  # each attempt builds on the last patch, safety-checked vs original
    error, hint = report["error"], report.get("hint", "")
    custom = {p.name: p.read_text() for p in wf_path(wf_id).parent.glob("step_*.py")}

    while w["tries"] < MAX_PER_INCIDENT and day["count"] < MAX_PER_DAY:
        w["tries"] += 1
        day["count"] += 1
        write_json(HEAL, state)
        log(f"heal attempt {w['tries']}/{MAX_PER_INCIDENT} for {wf_id} (incident {incident})", "heal")
        prompt = (f"BLOCKS:\n{catalog()}\n\nSPEC (yaml):\n{yaml.safe_dump(original, sort_keys=False)}\n"
                  f"CUSTOM CODE FILES: {json.dumps(custom)[:4000]}\n\n"
                  f"FAILED STEP: {report['step']}\nERROR: {error}\nEVIDENCE:\n{hint[:5000]}\n\n"
                  'Return {"diagnosis": "<one sentence>", "fixable": true|false, '
                  '"spec": <full patched spec as a JSON object>, "files": {"step_x.py": "<full code>"} }\n'
                  "Custom code is optional: only via the python block, files MUST be named step_<name>.py, "
                  "define run(ctx, **args), and may use requests.get + bs4 only. Prefer fixing block args. "
                  "For a failing `code` step, just fix its with.source in the spec.")
        try:
            ans = chat_json(prompt, SYSTEM)
        except Exception as e:  # noqa: BLE001
            log(f"brain stumbled: {e}", "err")
            error = f"{error} (your last answer was not valid JSON; reply with clean JSON)"
            continue
        diagnosis = ans.get("diagnosis", "?")
        log(f"diagnosis: {diagnosis}", "heal")
        if not ans.get("fixable", True) or not isinstance(ans.get("spec"), dict):
            rollback_and_pause(wf_id, diagnosis)
            return "gave_up"
        patched = ans["spec"]
        try:
            safety.check_heal(original, patched)
            for code in (ans.get("files") or {}).values():
                safety.check_code(code)
        except safety.SafetyError as e:
            log(f"patch refused by safety gate: {e}", "warn")
            error, hint = f"previous patch refused: {e}", hint
            continue
        # sandbox: write patch, dry-run with tests; restore if it fails
        backup_spec, backup_files = wf_path(wf_id).read_text(), dict(custom)
        save_spec(wf_id, patched)
        for name, code in (ans.get("files") or {}).items():
            if name.startswith("step_") and name.endswith(".py"):
                (wf_path(wf_id).parent / name).write_text("# ⚒ NIXFORGE · healed step — forged by Swanix 🐸\n" + code)
        try:
            execute(wf_id, patched, report.get("inputs"), dry=True)
        except StepError as e:
            log(f"patch failed its sandbox test: {e}", "warn")
            wf_path(wf_id).write_text(backup_spec)
            for p in wf_path(wf_id).parent.glob("step_*.py"):
                if p.name not in backup_files:
                    p.unlink()
            for name, code in backup_files.items():
                (wf_path(wf_id).parent / name).write_text(code)
            error, hint = f"after your last patch (step {getattr(e, 'step', '?')}): {e}", e.hint or hint
            current = patched
            continue
        # promoted: on probation until its next real run goes green
        w.update(probation=True, tries=0, last_fix=diagnosis,
                 healed_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
        write_json(HEAL, state)
        (REPORT_DIR / f"{wf_id}.json").unlink(missing_ok=True)
        w.pop("broken_since", None)
        write_json(HEAL, state)
        _out(healed="true", diagnosis=json.dumps(diagnosis))
        return "healed"

    rollback_and_pause(wf_id, f"{MAX_PER_INCIDENT} fix attempts didn't work (last error: {error[:160]})")
    return "gave_up"


def main(argv=None) -> int:
    banner()
    argv = argv or sys.argv[1:]
    result = heal(argv[0])
    _out(result=result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
