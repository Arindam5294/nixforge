# ⚒ NIXFORGE changelog

## v0.4.4 — no more blank pages
- Websites are written with a long-output brain (up to 32k tokens) and auto-continued if the model stops mid-file.
- Proven three.js skeleton in the prompt; scripts that use import are auto-promoted to modules.
- Structural check (cut-off file, no script, canvas nobody draws on) on top of the headless-Chrome check.

## v0.4.3 — sites that actually work
- New h.build_site(): art-director prompt, auto-fixed three.js imports (importmap), then a real headless-Chrome check (JS errors, blank 3D canvas, empty page) with up to 3 rewrite rounds. Sends you a screenshot with the link.
- Planner always uses it for websites, stores, apps, games and 3D.

## v0.4.2 — answers first
- Every request runs right away and replies with the result (no silent approval wait). Scheduled ones stay on; /pause to stop.
- New update channel: patches/*.url files apply a patch.

## v0.4.1 — brains back
- Gemini walks a list of live models (2.0-flash was retired → 2.5-flash).
- Groq/OpenRouter retry without JSON mode and fall back to smaller models on 400; errors show the API reason.

## v0.1 · 2026-10-19
- first forge: planner, runner, healer, evolution pitches, Telegram bot, dashboard
- heal demo verified live on GitHub Actions: h2.page-title broke, healed to h1.forge-title, promoted
- setup hardening: Codespace GPG-signing hang fixed, force-push over starter README, Cloudflare token check, real gh login for workflow dispatch, `scripts/worker.sh` for Worker-only redeploys
- forged by Swanix 🐸

## v0.2 · 2026-10-19 · E1
- 🧬 evolved: Periodic Messaging (new block `repeat`)
- why: Enables sending repeated messages at set intervals, filling the gap for timed notifications
- approved by Swanix 🐸

## v0.3 · 2026-10-19 · E2
- 🧬 evolved: 3D Website Builder (new block `threejs_build`)
- why: Enables users to generate interactive 3D web pages using Three.js without external services.
- approved by Swanix 🐸

## v0.4 · 2026-10-20 · the universal forge
- ⚒ new `code` block: the planner writes real Python for ANY request (APIs, scraping, loops, files, websites) instead of pitching upgrades
- 🌐 `h.publish()` hosts generated sites/files and returns a public link; results land on Telegram
- ▶️ Approve in Telegram now runs the workflow instantly (push trigger), scheduled ones get their first run right away
- 🩹 healer reads tracebacks and rewrites broken code silently
- 🧹 retired the hollow `repeat` / `threejs_build` evolutions and their test workflows
- forged by Swanix 🐸
