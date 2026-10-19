# ─────────────────────────────────────────────────────────────
#  ⚒  NIXFORGE · sig.py — the maker's mark
#  forged by Swanix 🐸  ·  "describe it. forge it. it heals."
# ─────────────────────────────────────────────────────────────
"""Every forge leaves a mark. This is Swanix's.

Banner, logger and commit trailer used by every NIXFORGE module, so each log
line, Telegram message and git commit carries the same signature.
"""
import os
import sys
import time

MAKER = "Swanix"
MARK = "🐸⚒"
TAGLINE = "describe it. forge it. it heals."
TRAILER = "Forged-by: Swanix <nixforge>"
SIGN_OFF = f"— forged by {MAKER} {MARK}"

BANNER = r"""
   _  _ _____  _____ ___  ___  ___ ___
  | \| |_ _\ \/ / __/ _ \| _ \/ __| __|      ()-()
  | .` || | >  <| _| (_) |   / (_ | _|     .-(___)-.
  |_|\_|___/_/\_\_| \___/|_|_\\___|___|     _<   >_
                                           \/     \/
        describe it. forge it. it heals.   — by Swanix 🐸
"""

_ICONS = {"info": "🐸", "ok": "✅", "warn": "⚠️ ", "err": "💥", "heal": "🩹", "forge": "⚒ "}


def banner() -> None:
    if not os.environ.get("NIXFORGE_QUIET"):
        print(BANNER, file=sys.stderr)


def log(msg: str, kind: str = "info") -> None:
    """ribbit-style log line: 🐸 [nixforge 12:03:44] message"""
    stamp = time.strftime("%H:%M:%S")
    print(f"{_ICONS.get(kind, '🐸')} [nixforge {stamp}] {msg}", file=sys.stderr, flush=True)


def stamp(text: str) -> str:
    """Sign a message the way Swanix signs things."""
    return f"{text}\n\n{SIGN_OFF}"
