#!/usr/bin/env bash
# ⚒ NIXFORGE · deploy just the Worker (bot voice + dashboard) — forged by Swanix 🐸
set -euo pipefail
# Codespace token can't dispatch workflows: use a real gh login
unset GITHUB_TOKEN; gh auth status >/dev/null 2>&1 || gh auth login -h github.com -p https -w -s repo,workflow
cd "$(dirname "$0")/.."
ask(){ local v; read -r -s -p "🔑 $1: " v; echo >&2; echo "$v"; }
[ -n "${CLOUDFLARE_ACCOUNT_ID:-}" ] && export CLOUDFLARE_ACCOUNT_ID
CF=$(ask "Cloudflare API token")
curl -s -H "Authorization: Bearer $CF" https://api.cloudflare.com/client/v4/user/tokens/verify | grep -q '"active"' \
  || { echo "💥 Cloudflare says that token isn't valid. Copy it again (whole thing) and rerun."; exit 1; }
echo "✅ Cloudflare token OK"
TG=$(ask "Telegram bot token")
GRQ=$(ask "Groq API key (Enter to skip)")
GEM=$(ask "Gemini API key (Enter to skip)")
CHAT=$(curl -s "https://api.telegram.org/bot$TG/getUpdates" | python3 -c "import sys,json;r=json.load(sys.stdin).get('result',[]);print(next((u['message']['chat']['id'] for u in reversed(r) if 'message' in u),''))")
[ -z "$CHAT" ] && { echo "💥 Send /start to your bot in Telegram, then rerun."; exit 1; }
export CLOUDFLARE_API_TOKEN="$CF"
cd worker
OUT=$(npx -y wrangler@3 deploy 2>&1) || { echo "$OUT" | tail -15; exit 1; }
URL=$(echo "$OUT" | grep -oE 'https://[a-z0-9.-]+\.workers\.dev' | head -1)
HOOK=$(python3 -c "import secrets;print(secrets.token_hex(16))")
put(){ printf '%s' "$2" | npx -y wrangler@3 secret put "$1" >/dev/null; }
put TELEGRAM_BOT_TOKEN "$TG"; put OWNER_CHAT_ID "$CHAT"; put WEBHOOK_SECRET "$HOOK"; put GH_TOKEN "$(gh auth token)"
[ -n "$GRQ" ] && put GROQ_API_KEY "$GRQ"
[ -n "$GEM" ] && put GEMINI_API_KEY "$GEM"
cd ..
curl -s "https://api.telegram.org/bot$TG/setWebhook" -d "url=$URL/tg/$HOOK" -d 'allowed_updates=["message","callback_query"]' >/dev/null
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
gh workflow run forge.yml -R "$REPO" -f wf=heal-demo
curl -s "https://api.telegram.org/bot$TG/sendMessage" -d chat_id="$CHAT" --data-urlencode text="⚒ NIXFORGE is lit. At your service, Swanix.
Dashboard: $URL

— forged by Swanix 🐸⚒" >/dev/null
echo "⚒ Done. Worker live: $URL"
echo "   Heal demo running: it fails on purpose, heals itself, then pings you (~3–8 min)."
echo "   — forged by Swanix 🐸"
