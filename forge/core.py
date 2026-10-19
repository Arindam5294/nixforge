# ─────────────────────────────────────────────────────────────
#  ⚒  NIXFORGE · core.py — paths, state, templating, safe eval
#  forged by Swanix 🐸
# ─────────────────────────────────────────────────────────────
import json
import os
import re
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("NIXFORGE_ROOT", Path(__file__).resolve().parent.parent))
WF_DIR = ROOT / "workflows"
STATE_DIR = ROOT / "state"
REPORT_DIR = ROOT / "reports"
GREEN_DIR = STATE_DIR / "_green"


class StepError(Exception):
    """A step failed. `hint` carries evidence the healer can reason over."""

    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.hint = hint


# ── workflows ────────────────────────────────────────────────
def wf_path(wf_id: str) -> Path:
    return WF_DIR / wf_id / "spec.yaml"


def load_spec(wf_id: str) -> dict:
    return yaml.safe_load(wf_path(wf_id).read_text())


def save_spec(wf_id: str, spec: dict) -> None:
    p = wf_path(wf_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# ⚒ NIXFORGE workflow — forged by Swanix 🐸\n" + yaml.safe_dump(spec, sort_keys=False, allow_unicode=True))


def all_workflows() -> list[str]:
    return sorted(p.parent.name for p in WF_DIR.glob("*/spec.yaml"))


# ── tiny JSON state (lives in git, so it has history for free) ──
def read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# ── {{ templating }} ─────────────────────────────────────────
_TPL = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


def lookup(path: str, ctx: dict):
    cur = ctx
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        else:
            cur = getattr(cur, part, None)
    return cur


def render(value, ctx: dict):
    """Fill {{ step.field }} placeholders. A lone placeholder keeps its type."""
    if isinstance(value, str):
        m = _TPL.fullmatch(value.strip())
        if m:
            return lookup(m.group(1), ctx)
        return _TPL.sub(lambda mm: "" if lookup(mm.group(1), ctx) is None else str(lookup(mm.group(1), ctx)), value)
    if isinstance(value, list):
        return [render(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: render(v, ctx) for k, v in value.items()}
    return value


_SAFE = {"len": len, "any": any, "all": all, "str": str, "int": int, "float": float,
         "bool": bool, "min": min, "max": max, "True": True, "False": False, "None": None}


class Dot(dict):
    """dict that also allows watch.changed style access inside tests."""
    def __getattr__(self, k):
        try:
            v = self[k]
        except KeyError as e:
            raise AttributeError(k) from e
        return Dot(v) if isinstance(v, dict) else v


def safe_eval(expr: str, ctx: dict):
    """Evaluate a test/condition like `len(headline) > 0` over step outputs."""
    if any(bad in expr for bad in ("__", "import", "open(", "exec", "eval", "lambda")):
        raise ValueError(f"unsafe expression: {expr}")
    env = {k: (Dot(v) if isinstance(v, dict) else v) for k, v in ctx.items()}
    return eval(expr, {"__builtins__": {}}, {**_SAFE, **env})  # noqa: S307 — sandboxed
