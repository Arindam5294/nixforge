# ─────────────────────────────────────────────────────────────
#  ⚒  NIXFORGE · blocks.py — the anvil's toolkit
#  forged by Swanix 🐸  ·  every outside call: retry ×3, then a fallback
# ─────────────────────────────────────────────────────────────
"""Building blocks the planner composes and the healer may re-tune.

Each block declares whether it has side effects. In a dry run (the healer's
sandbox) side-effect blocks never fire. Messages only ever go to the owner.
"""
import difflib
import json
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


# ── the universal block: real Python, written by the planner, healed by the healer ──
CODE_HELP = """code(source) -> runs `def run(h):` and returns its result. h gives you:
  h.inputs (dict)  h.now (str)  h.prev (earlier step outputs)  h.dry (True while testing)
  h.get(url, **kw) -> requests.Response (retries)   h.post(url, **kw) -> requests.Response
  h.fetch(url) -> page text (falls back to a reader)  h.soup(html) -> BeautifulSoup
  h.llm(prompt, system=None) -> text from the free LLM chain (big outputs OK)
  h.notify(text) -> Telegram message to the OWNER     h.send_file(path, caption='')
  h.publish(filename, content) -> public URL of a hosted file (html sites, json, txt)
  h.build_site(brief) -> URL: designs, writes, browser-tests and publishes a website / web app / game / 3D page,
      and sends the owner a screenshot. ALWAYS use this for any site/app/game/3D request (brief = full detailed request).
  h.changed(key, value) -> True only when value differs from last run (first run False)
  h.state -> dict saved between runs   h.sleep(s)   h.log(msg)   h.tmp -> temp dir Path
  any pip lib already installed: requests, bs4, feedparser, yaml, yt-dlp; ffmpeg on PATH."""


class Helpers:
    def __init__(self, ctx):
        self._ctx, self.dry = ctx, bool(ctx.get("_dry"))
        self.inputs, self.now = ctx.get("inputs", {}), ctx.get("now", "")
        self.prev = {k: v for k, v in ctx.items() if not k.startswith("_") and k not in ("inputs", "now")}
        self._spath = STATE_DIR / f"{ctx['_wf']}.code.json"
        self.state = read_json(self._spath, {})
        self.tmp = Path(tempfile.mkdtemp(prefix="nixforge-"))
        self.sent: list = []

    def get(self, url, **kw):
        kw.setdefault("headers", UA)
        kw.setdefault("timeout", 30)
        return retry(lambda: requests.get(url, **kw))

    def post(self, url, **kw):
        kw.setdefault("timeout", 60)
        return retry(lambda: requests.post(url, **kw))

    def fetch(self, url):
        return fetch(self._ctx, url)

    def soup(self, html):
        from bs4 import BeautifulSoup
        return BeautifulSoup(html or "", "html.parser")

    def llm(self, prompt, system=None):
        from .llm import chat
        return chat(prompt, system or "You are a precise, helpful expert. Follow the format asked exactly.")

    def notify(self, text):
        self.sent.append(str(text)[:200])
        if self.dry:
            log(f"[dry-run] would notify: {str(text)[:120]}")
            return "dry"
        return telegram(self._ctx, str(text))

    def send_file(self, path, caption=""):
        if self.dry:
            log(f"[dry-run] would send file {path}")
            return "dry"
        with open(path, "rb") as f:
            return _tg("sendDocument", caption=f"{caption}\n{SIGN_OFF}"[:1000], files={"document": f})

    def publish(self, filename, content):
        from .core import ROOT
        repo = os.environ.get("GITHUB_REPOSITORY", "Arindam5294/nixforge")
        name = Path(str(filename)).name or "index.html"
        url = f"https://raw.githack.com/{repo}/main/out/{self._ctx['_wf']}/{name}"
        if not self.dry:
            out = ROOT / "out" / self._ctx["_wf"] / name
            out.parent.mkdir(parents=True, exist_ok=True)
            (out.write_bytes if isinstance(content, bytes) else out.write_text)(content)
            self._ctx.setdefault("_published", []).append(str(out))
        return url

    def build_site(self, brief, filename="index.html"):
        """Design + write + browser-test a website/game/3D page, publish it, send a screenshot. Returns URL."""
        from .sitebuilder import build_site
        if self.dry:
            log("[dry-run] would build site")
            return self.publish(filename, "<!DOCTYPE html><title>dry</title>")
        html, shot, problems = build_site(str(brief), self.tmp)
        url = self.publish(filename, html)
        self.publish("build-report.json", json.dumps({"problems_left": problems, "browser_checked": bool(shot)}, indent=1))
        if shot:
            self.publish("preview.png", Path(shot).read_bytes())
            self.send_file(str(shot), f"🖼 Preview\n{url}")
        return url

    def changed(self, key, value):
        mem = self.state.setdefault("_seen", {})
        new = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
        old = mem.get(key)
        mem[key] = new
        return old is not None and old != new

    def sleep(self, s):
        if not self.dry:
            time.sleep(min(float(s), 600))

    def log(self, msg):
        log(str(msg)[:300])

    def _save(self):
        if not self.dry:
            write_json(self._spath, self.state)


@block("code", side_effect=True, doc=CODE_HELP)
def code(ctx, source: str):
    import traceback
    from .safety import check_code_block
    check_code_block(source)
    h = Helpers(ctx)
    ns: dict = {"__name__": f"nixforge_{ctx['_wf']}"}
    try:
        exec(compile(source, f"<{ctx['_wf']}>", "exec"), ns)  # noqa: S102 — owner-approved code on his own runner
        if "run" not in ns:
            raise StepError("code must define run(h)")
        result = ns["run"](h)
    except StepError:
        raise
    except Exception as e:  # noqa: BLE001
        numbered = "\n".join(f"{i + 1:3} {ln}" for i, ln in enumerate(source.splitlines()))
        raise StepError(f"{type(e).__name__}: {e}",
                        hint=f"TRACEBACK:\n{traceback.format_exc()[-2500:]}\n\nSOURCE:\n{numbered[:3500]}") from e
    h._save()
    return result if result is not None else "done"


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
