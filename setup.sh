#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  ⚒  NIXFORGE · setup.sh — light the forge in one go
#  forged by Swanix 🐸  ·  run inside your Codespace: bash setup.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"
G='\033[1;32m'; C='\033[1;36m'; M='\033[1;35m'; Y='\033[1;33m'; N='\033[0m'
say(){ echo -e "${C}🐸 $*${N}"; }
ok(){ echo -e "${G}✅ $*${N}"; }
ask(){ local v; read -r -s -p "$(echo -e "${Y}🔑 $1: ${N}")" v; echo >&2; echo "$v"; }

echo -e "${M}"
cat <<'ART'
   _  _ _____  _____ ___  ___  ___ ___
  | \| |_ _\ \/ / __/ _ \| _ \/ __| __|      ()-()
  | .` || | >  <| _| (_) |   / (_ | _|     .-(___)-.
  |_|\_|___/_/\_\_| \___/|_|_\\___|___|     _<   >_
        describe it. forge it. it heals.   — by Swanix 🐸
ART
echo -e "${N}"

# 1) GitHub login with repo + workflow scope (Codespace tokens can't create repos)
unset GITHUB_TOKEN GH_TOKEN || true
if ! gh auth status -h github.com >/dev/null 2>&1 || ! gh auth status 2>&1 | grep -q workflow; then
  say "Logging in to GitHub. Copy the code it shows, open the link, paste it."
  gh auth login -h github.com -p https -s repo,workflow -w
fi
OWNER=$(gh api user -q .login); REPO="$OWNER/nixforge"
ok "GitHub: $OWNER"

# 2) Secrets (typed hidden, never printed, never committed)
say "Make a NEW Telegram bot: open @BotFather → /newbot → copy the token."
TG=$(ask "Telegram bot token")
say "Free AI keys. Paste the ones you have, press Enter to skip (need at least one)."
GEM=$(ask "Gemini API key (aistudio.google.com)")
GRQ=$(ask "Groq API key (console.groq.com)")
ORT=$(ask "OpenRouter API key (openrouter.ai)")
[ -z "$GEM$GRQ$ORT" ] && { echo "💥 Need at least one AI key."; exit 1; }
say "Cloudflare token: dash.cloudflare.com/profile/api-tokens → Create → 'Edit Cloudflare Workers' template."
CF=$(ask "Cloudflare API token")

# 3) Find your Telegram chat id
say "Now open your new bot in Telegram and send it /start  (waiting…)"
CHAT=""
curl -s "https://api.telegram.org/bot$TG/deleteWebhook" >/dev/null
for i in $(seq 1 60); do
  CHAT=$(curl -s "https://api.telegram.org/bot$TG/getUpdates" | python3 -c "import sys,json;r=json.load(sys.stdin).get('result',[]);print(r[-1]['message']['chat']['id'] if r and 'message' in r[-1] else '')" 2>/dev/null || true)
  [ -n "$CHAT" ] && break; sleep 3
done
[ -z "$CHAT" ] && { echo "💥 Didn't see your /start. Run setup again."; exit 1; }
ok "Telegram chat linked"

# 4) Create the repo and push (every commit carries the maker's mark)
sed -i "s#Arindam5294/nixforge#$REPO#g" worker/wrangler.toml workflows/heal-demo/spec.yaml README.md || true
git init -q -b main 2>/dev/null || true
git config user.name "$OWNER"; git config user.email "$OWNER@users.noreply.github.com"
git add -A
git -c commit.gpgsign=false commit -q -m "⚒ NIXFORGE v$(cat VERSION): the forge is lit" -m "Forged-by: Swanix <nixforge>" || true
if gh repo view "$REPO" >/dev/null 2>&1; then
  git remote remove origin 2>/dev/null || true; git remote add origin "https://github.com/$REPO.git"; git push -u --force origin main
else
  gh repo create "$REPO" --public --description "⚒ Describe any automation in plain words. NIXFORGE forges it, runs it, and heals itself. — by Swanix 🐸" --source . --push
fi
ok "Repo: https://github.com/$REPO"

# 5) GitHub secrets for the runners
gh secret set TELEGRAM_BOT_TOKEN -R "$REPO" -b "$TG"
gh secret set TELEGRAM_CHAT_ID   -R "$REPO" -b "$CHAT"
[ -n "$GEM" ] && gh secret set GEMINI_API_KEY     -R "$REPO" -b "$GEM"
[ -n "$GRQ" ] && gh secret set GROQ_API_KEY       -R "$REPO" -b "$GRQ"
[ -n "$ORT" ] && gh secret set OPENROUTER_API_KEY -R "$REPO" -b "$ORT"
ok "GitHub secrets set"

# 6) Cloudflare Worker (the bot's voice + dashboard)
export CLOUDFLARE_API_TOKEN="$CF" CLOUDFLARE_ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-}"
curl -s -H "Authorization: Bearer $CF" https://api.cloudflare.com/client/v4/user/tokens/verify | grep -q '"active"' || { echo "💥 Cloudflare token not valid. Fix it, then run: bash scripts/worker.sh"; exit 1; }
cd worker
OUT=$(npx -y wrangler@3 deploy 2>&1) || { echo "$OUT"; exit 1; }
URL=$(echo "$OUT" | grep -oE 'https://[a-z0-9.-]+\.workers\.dev' | head -1)
HOOK=$(python3 -c "import secrets;print(secrets.token_hex(16))")
put(){ printf '%s' "$2" | npx -y wrangler@3 secret put "$1" >/dev/null; }
put TELEGRAM_BOT_TOKEN "$TG"; put OWNER_CHAT_ID "$CHAT"; put WEBHOOK_SECRET "$HOOK"
put GH_TOKEN "$(gh auth token)"
[ -n "$GRQ" ] && put GROQ_API_KEY "$GRQ"
[ -n "$GEM" ] && put GEMINI_API_KEY "$GEM"
cd ..
curl -s "https://api.telegram.org/bot$TG/setWebhook" -d "url=$URL/tg/$HOOK" -d 'allowed_updates=["message","callback_query"]' >/dev/null
ok "Worker live: $URL"

# 7) Prove it: run the broken-on-purpose demo; the forge heals it by itself
gh workflow enable forge.yml -R "$REPO" >/dev/null 2>&1 || true
gh workflow run forge.yml -R "$REPO" -f wf=heal-demo
curl -s "https://api.telegram.org/bot$TG/sendMessage" -d chat_id="$CHAT" \
  --data-urlencode text="⚒ NIXFORGE is lit. At your service, Swanix.
Dashboard: $URL
Tell me anything you want automated, in plain words.

— forged by Swanix 🐸⚒" >/dev/null

echo
echo -e "${M}⚒ Done. The forge is lit.${N}"
echo -e "   Dashboard: ${C}$URL${N}"
echo -e "   Heal demo is running now: it fails on purpose, heals itself, then messages you on Telegram (~3–8 min)."
echo -e "   Watch: https://github.com/$REPO/actions"
echo -e "${G}   — forged by Swanix 🐸${N}"
