# ─────────────────────────────────────────────────────────────
#  ⚒  NIXFORGE · runner.py — strikes the steps, one by one
#  forged by Swanix 🐸
# ─────────────────────────────────────────────────────────────
"""Run workflows.

  python -m forge.runner run <id> [--dry] [--input k=v ...]
  python -m forge.runner due            # cron tick: run whatever is due

A failed real run writes reports/<id>.json (error, step, evidence, traceback)
and prints its id so the heal job can pick it up.
"""
import argparse
import datetime as dt
import json
import os
import shutil
import sys
import traceback
from zoneinfo import ZoneInfo

from croniter import croniter

from . import safety
from .blocks import REGISTRY
from .core import (GREEN_DIR, REPORT_DIR, STATE_DIR, StepError, all_workflows, load_spec, read_json,
                   render, safe_eval, wf_path, write_json)
from .sig import banner, log

RUNS = STATE_DIR / "_runs.json"


class TestFailure(StepError):
    pass


def execute(wf_id: str, spec: dict, inputs: dict | None = None, dry: bool = False) -> dict:
    """Run every step; raise StepError (with .step) on the first failure."""
    safety.check_spec(spec)
    ctx = {"_wf": wf_id, "_dry": dry, "inputs": {**(spec.get("inputs") or {}), **(inputs or {})},
           "now": dt.datetime.now(ZoneInfo(spec.get("tz", "Asia/Kolkata"))).strftime("%d %b %Y %H:%M")}
    for step in spec["steps"]:
        sid = step["id"]
        if "when" in step and not render(step["when"], ctx) and not safe_eval_maybe(step["when"], ctx):
            log(f"skip {sid} (when is false)")
            ctx[sid] = None
            continue
        args = render(step.get("with", {}), ctx)
        log(f"step {sid} ← {step['use']}", "forge")
        try:
            ctx[sid] = REGISTRY[step["use"]]["fn"](ctx, **args)
        except StepError as e:
            e.step = sid
            raise
        except Exception as e:  # noqa: BLE001
            err = StepError(f"{type(e).__name__}: {e}")
            err.step = sid
            raise err from e
    for t in spec.get("tests") or []:
        ok = False
        try:
            ok = bool(safe_eval(t, {k: v for k, v in ctx.items() if not k.startswith("_")}))
        except Exception as e:  # noqa: BLE001
            raise TestFailure(f"test '{t}' crashed: {e}") from e
        if not ok:
            err = TestFailure(f"test failed: {t}")
            err.step = "tests"
            raise err
    return ctx


def safe_eval_maybe(expr, ctx):
    if not isinstance(expr, str) or "{{" in expr:
        return False
    try:
        return bool(safe_eval(expr, {k: v for k, v in ctx.items() if not k.startswith("_")}))
    except Exception:  # noqa: BLE001
        return False


def record(wf_id: str, ok: bool, note: str) -> None:
    runs = read_json(RUNS, {})
    hist = runs.setdefault(wf_id, [])
    hist.insert(0, {"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "ok": ok, "note": note[:300]})
    del hist[20:]
    write_json(RUNS, runs)


def run_real(wf_id: str, inputs: dict | None = None) -> bool:
    spec = load_spec(wf_id)
    try:
        execute(wf_id, spec, inputs)
    except StepError as e:
        log(f"{wf_id} failed at {getattr(e, 'step', '?')}: {e}", "err")
        write_json(REPORT_DIR / f"{wf_id}.json", {
            "wf": wf_id, "step": getattr(e, "step", "?"), "error": str(e), "hint": e.hint[:6000],
            "trace": traceback.format_exc()[-3000:], "inputs": inputs or {},
            "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        })
        record(wf_id, False, str(e))
        return False
    # green run: remember this exact version as the rollback point
    GREEN_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy(wf_path(wf_id), GREEN_DIR / f"{wf_id}.yaml")
    (REPORT_DIR / f"{wf_id}.json").unlink(missing_ok=True)
    heal = read_json(STATE_DIR / "_heal.json", {})
    if heal.get(wf_id, {}).get("probation"):
        heal[wf_id]["probation"] = False
        write_json(STATE_DIR / "_heal.json", heal)
    record(wf_id, True, "ok")
    log(f"{wf_id} ✓ green", "ok")
    return True


def due(now: dt.datetime | None = None) -> list[str]:
    now = now or dt.datetime.now(dt.timezone.utc)
    runs = read_json(RUNS, {})
    out = []
    for wf in all_workflows():
        spec = load_spec(wf)
        if spec.get("status", "active") != "active" or not spec.get("schedule"):
            continue
        tz = ZoneInfo(spec.get("tz", "Asia/Kolkata"))
        last = runs.get(wf, [{}])[0].get("at")
        base = dt.datetime.fromisoformat(last) if last else now - dt.timedelta(minutes=16)
        nxt = croniter(spec["schedule"], base.astimezone(tz)).get_next(dt.datetime)
        if nxt <= now.astimezone(tz):
            out.append(wf)
    return out


def emit_failed(failed: list[str]) -> None:
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"failed={json.dumps(failed)}\n")
    print(json.dumps({"failed": failed}))


def main(argv=None) -> int:
    banner()
    ap = argparse.ArgumentParser(prog="nixforge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("wf")
    r.add_argument("--dry", action="store_true")
    r.add_argument("--input", action="append", default=[])
    sub.add_parser("due")
    a = ap.parse_args(argv)

    if a.cmd == "run":
        inputs = dict(kv.split("=", 1) for kv in a.input if "=" in kv)
        if a.dry:
            execute(a.wf, load_spec(a.wf), inputs, dry=True)
            log("dry run passed", "ok")
            return 0
        emit_failed([] if run_real(a.wf, inputs) else [a.wf])
        return 0
    failed = [wf for wf in due() if not run_real(wf)]
    emit_failed(failed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
