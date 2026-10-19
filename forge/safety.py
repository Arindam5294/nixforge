# ─────────────────────────────────────────────────────────────
#  ⚒  NIXFORGE · safety.py — the guard at the forge door
#  forged by Swanix 🐸  ·  rules live in code, not in prompts
# ─────────────────────────────────────────────────────────────
"""Hard rules every planned or healed workflow must pass.

1. Only known blocks. 2. No new side effects from a heal. 3. No secrets in
specs. 4. Custom code can't shell out, delete files, open sockets or send mail.
5. Spending money, public posting, messaging others and deleting data are not
blocks at all, so a workflow simply cannot do them.
"""
import re

from .blocks import REGISTRY

ID_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9]{16,}|gsk_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_\-]{20,}|\d{8,10}:[A-Za-z0-9_-]{30,})")
BANNED_CODE = ["subprocess", "os.system", "os.popen", "rmtree", "os.remove", "os.unlink", ".unlink(",
               "socket", "smtplib", "eval(", "exec(", "__import__", "requests.post", "requests.delete",
               "requests.put", "shutil.move", "ctypes"]


class SafetyError(Exception):
    pass


def check_spec(spec: dict) -> None:
    steps = spec.get("steps") or []
    if not steps:
        raise SafetyError("workflow has no steps")
    seen = set()
    for s in steps:
        sid, use = s.get("id", ""), s.get("use", "")
        if not ID_RE.match(sid):
            raise SafetyError(f"bad step id '{sid}' (use snake_case)")
        if sid in seen:
            raise SafetyError(f"duplicate step id '{sid}'")
        seen.add(sid)
        if use not in REGISTRY:
            raise SafetyError(f"unknown block '{use}' in step '{sid}'")
        if use == "code":
            check_code_block((s.get("with") or {}).get("source", ""))
    if SECRET_RE.search(str(spec)):
        raise SafetyError("a secret-looking value is inside the spec; secrets belong in GitHub/Cloudflare secrets")


def check_code(code: str) -> None:
    for bad in BANNED_CODE:
        if bad in code:
            raise SafetyError(f"custom code uses a banned call: {bad}")


CODE_BANNED = ["os.environ", "os.getenv", "environ[", "rmtree", "smtplib", ".git/", "GITHUB_TOKEN",
               "TELEGRAM_BOT_TOKEN", "API_KEY", "shutdown", "os.kill", "fork("]


def check_code_block(code: str) -> None:
    """The code block runs on the owner's own throwaway Actions runner, so it may
    use the network and subprocesses; it may NOT read secrets or wipe files."""
    if not isinstance(code, str) or "def run" not in code:
        raise SafetyError("code step needs a `def run(h):` function")
    for bad in CODE_BANNED:
        if bad in code:
            raise SafetyError(f"code step uses a banned thing: {bad}")


def side_effects(spec: dict) -> list:
    return sorted((s["use"], str(s.get("with", {}).get("to", "owner")))
                  for s in spec.get("steps", []) if REGISTRY.get(s.get("use"), {}).get("side_effect"))


def check_heal(old: dict, new: dict) -> None:
    """A heal may change HOW a step works, never WHAT the workflow is allowed to do."""
    check_spec(new)
    if side_effects(new) != side_effects(old):
        raise SafetyError("heal tried to add/remove a side-effect step (messages, uploads); refused")
    for key in ("schedule", "tz", "owner", "status"):
        if old.get(key) != new.get(key):
            raise SafetyError(f"heal tried to change '{key}'; refused")
