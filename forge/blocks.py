# ─────────────────────────────────────────────────────────────
#  ⚒  NIXFORGE · blocks.py — the anvil's toolkit
#  forged by Swanix 🐸  ·  every outside call: retry ×3, then a fallback
# ─────────────────────────────────────────────────────────────
"""Building blocks the planner composes and the healer may re-tune.

Each block declares whether it has side effects. In a dry run (the healer's
sandbox) side-effect blocks never fire. Messages only ever go to the owner.
"""
import difflib
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import requests

from .core import STATE_DIR, StepError, read_json, write_json
from .sig import SIGN_OFF, log

REGISTRY: dict = {}
UA = {"User-Agent": "Mozilla/5.0 (NIXFORGE by Swanix; +github.com/Arindam5294/nixforge)"}


def block(name: str, side_effect: bool = False, doc: str = ""):
    def wrap(fn):
        REGISTRY[name] = {"fn": fn, "side_effect": side_effect, "doc": doc}
        return fn
    return wrap


def retry(fn, tries: int = 3, base: float = 1.5):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            log(f"retry {i + 1}/{tries}: {str(e)[:120]}", "warn")
            time.sleep(base ** (i + 1))
    raise last


# ── web ──────────────────────────────────────────────────────
@block("fetch", doc="fetch(url) -> page text/html. Falls back to the r.jina.ai reader.")
def fetch(ctx, url: str, timeout: int = 30):
    def direct():
        r = requests.get(url, headers=UA, timeout=timeout)
        r.raise_for_status()
        return r.text

    try:
        return retry(direct)
    except Exception as e:  # noqa: BLE001
        log(f"direct fetch failed ({e}); trying reader fallback", "warn")
        r = requests.get(f"https://r.jina.ai/{url}", timeout=timeout)
        r.raise_for_status()
        return r.text


def _outline(html: str, limit: int = 120) -> str:
    """Compact map of the page so the healer can pick a new selector:
    one line per distinct tag.class path, with sample text."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    seen, lines = set(), []
    for el in soup.find_all(True):
        if el.name in ("script", "style", "meta", "link", "head", "html", "br", "img", "svg", "path"):
            continue
        cls = "." + ".".join(el.get("class", [])) if el.get("class") else ""
        idd = f"#{el.get('id')}" if el.get("id") else ""
        parent = el.parent
        pcls = (parent.name + ("." + ".".join(parent.get("class", [])) if parent.get("class") else "")) if parent else ""
        sig = f"{pcls} > {el.name}{idd}{cls}"
        if sig in seen:
            continue
        seen.add(sig)
        txt = el.get_text(" ", strip=True)[:60]
        if txt or cls or idd:
            lines.append(f"{sig}  ::  {txt}")
        if len(lines) >= limit:
            break
    return "\n".join(lines)


@block("select", doc="select(html, css, all=false, attr=null) -> text of the match(es).")
def select(ctx, html: str, css: str, all: bool = False, attr: str | None = None):  # noqa: A002
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html or "", "html.parser")
    els = soup.select(css)
    if not els:
        raise StepError(f"selector '{css}' matched nothing", hint="PAGE OUTLINE:\n" + _outline(html or ""))
    vals = [(e.get(attr) if attr else e.get_text(" ", strip=True)) for e in els]
    return vals if all else vals[0]


@block("rss", doc="rss(urls, limit=5) -> list of {title, link, summary}.")
def rss(ctx, urls, limit: int = 5):
    import feedparser
    urls = [urls] if isinstance(urls, str) else urls
    items = []
    for u in urls:
        try:
            feed = retry(lambda: feedparser.parse(requests.get(u, headers=UA, timeout=30).content))
            for e in feed.entries[:limit]:
                items.append({"title": e.get("title", ""), "link": e.get("link", ""),
                              "summary": (e.get("summary", "") or "")[:400]})
        except Exception as e:  # noqa: BLE001 — one dead feed never kills the digest
            log(f"feed skipped {u}: {e}", "warn")
    if not items:
        raise StepError("no feed returned any items", hint=f"feeds tried: {urls}")
    return items


# ── memory ───────────────────────────────────────────────────
@block("diff", doc="diff(key, value) -> {changed, old, new, delta}. Remembers last value.")
def diff(ctx, key: str, value):
    path = STATE_DIR / f"{ctx['_wf']}.json"
    st = read_json(path, {})
    old = st.get(key)
    new = value if isinstance(value, str) else str(value)
    changed = old is not None and old != new
    delta = "\n".join(difflib.unified_diff((old or "").splitlines(), new.splitlines(), lineterm="", n=0))[:1500]
    if not ctx.get("_dry"):
        st[key] = new
        write_json(path, st)
    return {"changed": changed, "first": old is None, "old": old, "new": new, "delta": delta}


# ── brains ───────────────────────────────────────────────────
@block("llm", doc="llm(prompt) -> text, via the free Gemini→Groq→OpenRouter chain.")
def llm(ctx, prompt: str, system: str = "You are a concise assistant. Plain text, no markdown tables."):
    from .llm import chat
    return chat(prompt, system)


# ── owner-only outputs (side effects) ────────────────────────
def _tg(method: str, **kw):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise StepError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID secrets are missing")
    files = kw.pop("files", None)
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}", data={"chat_id": chat, **kw},
                      files=files, timeout=120)
    if r.status_code != 200:
        raise StepError(f"telegram {method} failed: {r.text[:200]}")
    return r.json()


@block("telegram", side_effect=True, doc="telegram(text, quiet=false) -> sends to the OWNER only.")
def telegram(ctx, text: str, quiet: bool = False):
    body = f"{text}\n\n{SIGN_OFF}"[:4000]
    if ctx.get("_dry"):
        return f"[dry-run] would send: {body[:120]}"
    retry(lambda: _tg("sendMessage", text=body, disable_web_page_preview="true",
                      disable_notification=str(bool(quiet)).lower()))
    return "sent"


@block("convert", side_effect=True, doc="convert(url, format='mp3') -> downloads, converts with ffmpeg, sends file to owner.")
def convert(ctx, url: str, format: str = "mp3"):  # noqa: A002
    fmt = format.lower().strip(".")
    work = Path(tempfile.mkdtemp(prefix="nixforge-"))
    src = None
    # 1) yt-dlp knows thousands of sites; 2) fallback: plain download
    if shutil.which("yt-dlp"):
        try:
            retry(lambda: subprocess.run(["yt-dlp", "-q", "--no-playlist", "-o", str(work / "src.%(ext)s"), url],
                                         check=True, timeout=600), tries=2)
            src = next(work.glob("src.*"), None)
        except Exception as e:  # noqa: BLE001
            log(f"yt-dlp failed, falling back to direct download: {e}", "warn")
    if src is None:
        r = retry(lambda: requests.get(url, headers=UA, timeout=120, stream=True))
        r.raise_for_status()
        src = work / ("src" + (Path(url.split("?")[0]).suffix or ".bin"))
        with open(src, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
    out = work / f"nixforge-{hashlib.md5(url.encode()).hexdigest()[:6]}.{fmt}"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), str(out)], check=True, timeout=900)
    size_mb = out.stat().st_size / 1e6
    if ctx.get("_dry"):
        return f"[dry-run] converted {out.name} ({size_mb:.1f} MB)"
    if size_mb > 49:
        raise StepError(f"result is {size_mb:.0f} MB; Telegram bots can send max 50 MB",
                        hint="try a lighter format (mp3/opus) or lower resolution")
    with open(out, "rb") as f:
        _tg("sendDocument", caption=f"⚒ {out.name}\n{SIGN_OFF}", files={"document": f})
    return out.name


# ── custom code (sandboxed by static rules in safety.py) ─────
@block("python", doc="python(file, **args) -> run(ctx, **args) from a step_*.py file in the workflow folder.")
def python_step(ctx, file: str, **args):
    import importlib.util
    from .core import WF_DIR
    from .safety import check_code
    path = WF_DIR / ctx["_wf"] / file
    check_code(path.read_text())
    spec = importlib.util.spec_from_file_location(f"nixforge_step_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run(ctx, **args)


def catalog() -> str:
    return "\n".join(f"- {n}{' [side effect]' if b['side_effect'] else ''}: {b['doc']}" for n, b in REGISTRY.items())


# ── evolved blocks (forge/blocks_ext/*.py), shipped only after owner approval ──
def _load_evolved():
    import importlib
    ext = Path(__file__).parent / "blocks_ext"
    for f in sorted(ext.glob("*.py")):
        if f.name != "__init__.py":
            try:
                importlib.import_module(f"forge.blocks_ext.{f.stem}")
            except Exception as e:  # noqa: BLE001 — a bad evolution never breaks the forge
                log(f"evolved block {f.stem} failed to load: {e}", "warn")


_load_evolved()
