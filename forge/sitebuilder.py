# ─────────────────────────────────────────────────────────────
#  ⚒  NIXFORGE · sitebuilder.py — websites, games and 3D that actually work
#  forged by Swanix 🐸
# ─────────────────────────────────────────────────────────────
"""h.build_site(brief) -> (html, screenshot_path | None, problems)

Writes a complete page with a design-director prompt, repairs the classic
three.js mistakes (bare 'three' imports without an importmap), then opens it
in headless Chromium: console errors, blank 3D canvas or empty page get fed
back to the model and it rewrites, up to 3 rounds."""
import re
import subprocess
import sys
from pathlib import Path

from .llm import chat
from .sig import log

THREE = "https://cdn.jsdelivr.net/npm/three@0.160.0"
IMPORTMAP = ('<script type="importmap">{"imports":{"three":"%s/build/three.module.js",'
             '"three/addons/":"%s/examples/jsm/"}}</script>' % (THREE, THREE))

SYSTEM = f"""You are an award-winning creative developer (Awwwards / FWA level) and art director.
You write ONE complete index.html (inline CSS + JS, no build step) that looks like a premium,
real product site, not a demo. Hard rules:
- Mobile-first and responsive; it will be opened on a phone first. Touch works everywhere.
- Real content: brand name, hero headline, sections (features/products/story/CTA/footer), believable copy, prices in ₹ or $ as fits.
- Typography from Google Fonts (pair a display + text font), a deliberate colour palette, generous spacing, smooth scroll-triggered reveal animations (IntersectionObserver), hover/tap micro-interactions.
- For 3D use three.js ONLY via this exact importmap in <head>: {IMPORTMAP}
  then `import * as THREE from 'three'` and addons like `import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js'`.
  Build the 3D subject procedurally so it is clearly VISIBLE and recognisable (e.g. a garment from LatheGeometry/ExtrudeGeometry/TubeGeometry,
  products on a podium, a scene with depth): MeshStandardMaterial/MeshPhysicalMaterial, key+rim+fill lights, RoomEnvironment for reflections,
  ACESFilmic tone mapping, soft shadows, gentle auto-rotation, camera framed so the subject fills the canvas. Never leave the canvas empty or black.
  Resize handler, devicePixelRatio capped at 2, requestAnimationFrame loop.
- Games: start screen, score, restart, keyboard + touch controls, sound via WebAudio.
- No external images that might 404; use CSS gradients, SVG, emoji or procedural canvas textures.
Return ONLY the HTML, starting with <!DOCTYPE html>."""


def _clean(txt: str) -> str:
    m = re.search(r"```(?:html)?\s*(.*?)```", txt, re.S)
    if m and "<html" in m.group(1).lower():
        txt = m.group(1)
    i = txt.find("<!")
    return (txt[i:] if i >= 0 else txt).strip()


def repair(html: str) -> str:
    """Deterministic fixes for the mistakes models make most."""
    html = re.sub(r"https://(?:unpkg\.com|cdn\.jsdelivr\.net/npm)/three@[\d.]+/build/three\.module(?:\.min)?\.js", "three", html)
    html = re.sub(r"https://(?:unpkg\.com|cdn\.jsdelivr\.net/npm)/three@[\d.]+/examples/jsm/", "three/addons/", html)
    html = re.sub(r"<script type=\"importmap\">.*?</script>", "", html, flags=re.S)
    if re.search(r"from\s+['\"]three(/addons/[^'\"]*)?['\"]", html):
        html = re.sub(r"<head([^>]*)>", lambda m: f"<head{m.group(1)}>\n{IMPORTMAP}", html, count=1, flags=re.I) \
            if re.search(r"<head", html, re.I) else IMPORTMAP + html
    if "viewport" not in html:
        html = re.sub(r"<head([^>]*)>", r'<head\1>\n<meta name="viewport" content="width=device-width,initial-scale=1">', html, count=1, flags=re.I)
    return html


def _browser_ready() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "playwright"], check=False)
    r = subprocess.run([sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"],
                       capture_output=True, text=True)
    if r.returncode:
        r = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], capture_output=True, text=True)
    return r.returncode == 0


def inspect(html: str, shot: Path) -> list[str]:
    """Open the page like a phone would. Returns problems ([] = looks good)."""
    from playwright.sync_api import sync_playwright
    page_file = shot.with_suffix(".html")
    page_file.write_text(html)
    problems: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
        pg = b.new_page(viewport={"width": 412, "height": 915}, device_scale_factor=2)
        pg.on("pageerror", lambda e: problems.append(f"JS error: {e}"))
        pg.on("console", lambda m: m.type == "error" and problems.append(f"console error: {m.text[:300]}"))
        pg.on("requestfailed", lambda r: problems.append(f"failed to load {r.url[:150]}"))
        pg.goto(page_file.as_uri(), wait_until="load", timeout=45000)
        pg.wait_for_timeout(3500)
        info = pg.evaluate("""() => {
          const out = {text: document.body ? document.body.innerText.trim().length : 0, canvases: []};
          for (const c of document.querySelectorAll('canvas')) {
            const r = c.getBoundingClientRect();
            if (r.width < 80 || r.height < 80) continue;
            let tmp = document.createElement('canvas'); tmp.width = 64; tmp.height = 64;
            const g = tmp.getContext('2d'); let vals = [];
            try { g.drawImage(c, 0, 0, 64, 64); const d = g.getImageData(0,0,64,64).data;
              for (let i = 0; i < d.length; i += 16) vals.push(d[i] + d[i+1] + d[i+2]); } catch (e) { vals = null; }
            if (!vals) { out.canvases.push(-1); continue; }
            const m = vals.reduce((a,b)=>a+b,0)/vals.length;
            out.canvases.push(Math.sqrt(vals.reduce((a,b)=>a+(b-m)**2,0)/vals.length));
          }
          return out; }""")
        pg.screenshot(path=str(shot), full_page=False)
        b.close()
    if info["text"] < 40 and not info["canvases"]:
        problems.append("page is basically empty: no visible text or canvas")
    if any(0 <= v < 6 for v in info["canvases"]):
        problems.append("the 3D/game canvas renders blank (flat colour): the subject is not visible; "
                        "check imports, camera position/lookAt, lights, object scale, and that render() runs every frame "
                        "(use preserveDrawingBuffer:true on the WebGLRenderer)")
    return list(dict.fromkeys(problems))[:12]


def build_site(brief: str, workdir: Path, rounds: int = 3):
    html = repair(_clean(chat(f"BRIEF: {brief}\n\nWrite the full index.html now.", SYSTEM)))
    shot, problems = None, []
    if not _browser_ready():
        log("sitebuilder: no headless browser, shipping unchecked")
        return html, None, ["not browser-checked"]
    for n in range(rounds):
        shot = workdir / f"shot{n}.png"
        try:
            problems = inspect(html, shot)
        except Exception as e:  # noqa: BLE001
            problems = [f"could not open page: {e}"]
        log(f"sitebuilder round {n + 1}: {problems or 'clean'}")
        if not problems or n == rounds - 1:
            break
        fix = chat(f"BRIEF: {brief}\n\nThis index.html has problems when opened in Chrome on a phone:\n- "
                   + "\n- ".join(problems) + f"\n\nCURRENT HTML:\n{html[:60000]}\n\n"
                   "Fix every problem and return the COMPLETE corrected index.html (keep and improve the design).", SYSTEM)
        html = repair(_clean(fix))
    return html, (shot if shot and shot.exists() else None), problems
