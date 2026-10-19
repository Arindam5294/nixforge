// ─────────────────────────────────────────────────────────────
//  ⚒  NIXFORGE · worker — the voice of the forge (Telegram + dashboard)
//  forged by Swanix 🐸  ·  "At your service, Swanix."
// ─────────────────────────────────────────────────────────────
// Talks like a butler, works like a forge. Only answers the owner's chat.
// Heavy lifting is dispatched to GitHub Actions; state is read from the repo.

const SIGN = "— forged by Swanix 🐸⚒";
const GH = "https://api.github.com";

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    if (req.method === "POST" && url.pathname === `/tg/${env.WEBHOOK_SECRET}`) {
      const update = await req.json();
      ctx.waitUntil(handle(update, env).catch((e) => say(env, `💥 ${e.message}`)));
      return new Response("ribbit");
    }
    if (url.pathname === "/api/status") return json(await status(env));
    if (url.pathname === "/" || url.pathname === "/index.html") return new Response(DASHBOARD, { headers: { "content-type": "text/html; charset=utf-8" } });
    return new Response("🐸 NIXFORGE — nothing here. " + SIGN, { status: 404 });
  },
};

// ── telegram ─────────────────────────────────────────────────
async function tg(env, method, body) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  });
  return r.json();
}
const say = (env, text, extra = {}) => tg(env, "sendMessage", { chat_id: env.OWNER_CHAT_ID, text, disable_web_page_preview: true, ...extra });

async function handle(update, env) {
  if (update.callback_query) return onButton(update.callback_query, env);
  const msg = update.message;
  if (!msg || String(msg.chat.id) !== String(env.OWNER_CHAT_ID)) return; // owner only
  const text = (msg.text || "").trim();
  if (!text) return;
  await tg(env, "sendChatAction", { chat_id: env.OWNER_CHAT_ID, action: "typing" });

  const [cmd, ...rest] = text.split(/\s+/);
  const arg = rest.join(" ");
  switch (cmd.toLowerCase().replace(/@.*$/, "")) {
    case "/start":
    case "/help": return say(env, HELP);
    case "/new": return forgeNew(env, arg);
    case "/list": return list(env);
    case "/run": return run(env, rest[0], rest.slice(1).join(" "));
    case "/pause": return setStatus(env, rest[0], "paused");
    case "/resume": return setStatus(env, rest[0], "active");
    case "/logs": return logs(env, rest[0]);
    case "/convert": return run(env, "convert", `url=${rest[0]} format=${rest[1] || "mp3"}`);
    case "/evolve": return dispatch(env, "evolve.yml", { pid: "" }).then(() => say(env, "🧬 Running a self-review. If I see a worthy upgrade, I'll pitch it."));
    case "/status": return statusMsg(env);
  }
  return jarvis(env, text); // plain words → understand → act
}

// Plain words: a free LLM routes intent, Jarvis-style.
async function jarvis(env, text) {
  const wfs = (await listWorkflows(env)).map((w) => w.id).join(", ");
  const sys = `You are NIXFORGE, Swanix's automation butler (think Jarvis): calm, witty, brief.
Existing workflows: ${wfs}.
Map the user's message to ONE action as JSON:
{"action":"new|run|pause|resume|list|logs|convert|status|chat","wf":"<id or null>","args":"<k=v pairs or request text>","reply":"<one short butler-style line>"}
"new" = they want something automated (args = their request, verbatim). "convert" args = "url=<link> format=<fmt>". "chat" = just talk.`;
  let a = { action: "new", args: text, reply: "Forging that now, sir." };
  try { a = await llmJSON(env, sys, text); } catch (_) { /* no brain → assume it's a new automation */ }
  switch (a.action) {
    case "new": await say(env, a.reply || "On it."); return forgeNew(env, a.args || text, true);
    case "run": return run(env, a.wf, a.args || "");
    case "pause": return setStatus(env, a.wf, "paused");
    case "resume": return setStatus(env, a.wf, "active");
    case "list": return list(env);
    case "logs": return logs(env, a.wf);
    case "convert": return run(env, "convert", a.args);
    case "status": return statusMsg(env);
    default: return say(env, a.reply || "At your service, Swanix.");
  }
}

async function llmJSON(env, system, user) {
  if (env.GROQ_API_KEY) {
    const r = await fetch("https://api.groq.com/openai/v1/chat/completions", {
      method: "POST", headers: { authorization: `Bearer ${env.GROQ_API_KEY}`, "content-type": "application/json" },
      body: JSON.stringify({ model: env.GROQ_MODEL || "openai/gpt-oss-120b", temperature: 0.3, response_format: { type: "json_object" },
        messages: [{ role: "system", content: system }, { role: "user", content: user }] }),
    });
    if (r.ok) return JSON.parse((await r.json()).choices[0].message.content);
  }
  if (env.GEMINI_API_KEY) {
    const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent`, {
      method: "POST", headers: { "x-goog-api-key": env.GEMINI_API_KEY, "content-type": "application/json" },
      body: JSON.stringify({ systemInstruction: { parts: [{ text: system }] }, contents: [{ role: "user", parts: [{ text: user }] }],
        generationConfig: { responseMimeType: "application/json" } }),
    });
    if (r.ok) return JSON.parse((await r.json()).candidates[0].content.parts[0].text);
  }
  throw new Error("no brain");
}

async function onButton(q, env) {
  if (String(q.message.chat.id) !== String(env.OWNER_CHAT_ID)) return;
  const [kind, id] = q.data.split(":");
  await tg(env, "answerCallbackQuery", { callback_query_id: q.id, text: "🐸 got it" });
  const done = (t) => tg(env, "editMessageText", { chat_id: q.message.chat.id, message_id: q.message.message_id, text: `${q.message.text}\n\n${t}` });
  if (kind === "approve") { await setStatus(env, slugDir(id), "active", true); return done("✅ Approved. It's live."); }
  if (kind === "discard") { await ghDelete(env, `workflows/${id}/spec.yaml`, `🗑 discard ${id}`); return done("🗑 Discarded."); }
  if (kind === "evolve" || kind === "shelve") {
    const f = await ghGet(env, "state/_evolution.json");
    const book = JSON.parse(f.text);
    if (!book.items[id]) return done("🤔 I can't find that pitch anymore.");
    book.items[id].status = kind === "evolve" ? "approved" : "shelved";
    await ghPut(env, "state/_evolution.json", JSON.stringify(book, null, 2), `🧬 ${kind} ${id} (approved by Swanix)`, f.sha);
    if (kind === "evolve") { await dispatch(env, "evolve.yml", { pid: id }); return done("🧬 Approved. Building and testing it now."); }
    return done("✋ Shelved. I won't bring it up again.");
  }
}
const slugDir = (s) => s;

// ── actions ──────────────────────────────────────────────────
async function forgeNew(env, request, quiet = false) {
  if (!request) return say(env, "Tell me what to automate, e.g.\n/new ping me when the GATE 2027 notices page changes");
  await dispatch(env, "plan.yml", { request });
  if (!quiet) await say(env, "⚒ Forging it. I'll send the plan for your approval in a minute or two.");
}

async function run(env, wf, inputs) {
  if (!wf) return say(env, "Which one? Send /list to see them.");
  await dispatch(env, "forge.yml", { wf, inputs: inputs || "" });
  return say(env, `▶️ Running ${wf}. GitHub can take a few minutes to start it.`);
}

async function setStatus(env, wf, to, silent = false) {
  if (!wf) return say(env, "Which one? Send /list to see them.");
  const path = `workflows/${wf}/spec.yaml`;
  const f = await ghGet(env, path);
  const next = /^status:/m.test(f.text) ? f.text.replace(/^status:.*$/m, `status: ${to}`) : f.text + `\nstatus: ${to}\n`;
  await ghPut(env, path, next, `🐸 ${to === "active" ? "resume" : "pause"} ${wf}`, f.sha);
  if (!silent) return say(env, `${to === "active" ? "▶️" : "⏸"} ${wf} is ${to}.`);
}

async function list(env) {
  const wfs = await listWorkflows(env);
  const icon = { active: "🟢", paused: "⏸", pending: "🕓" };
  const lines = wfs.map((w) => `${icon[w.status] || "⚪"} ${w.id}${w.schedule ? `  ⏰ ${w.schedule}` : "  ▶️ on demand"}`);
  return say(env, `⚒ Your forge\n\n${lines.join("\n") || "Nothing yet. Try /new"}\n\n${SIGN}`);
}

async function logs(env, wf) {
  const runs = JSON.parse((await raw(env, "state/_runs.json")) || "{}");
  const heal = JSON.parse((await raw(env, "state/_heal.json")) || "{}");
  const pick = wf ? { [wf]: runs[wf] || [] } : runs;
  const out = Object.entries(pick).map(([id, h]) => {
    const last = (h || []).slice(0, 3).map((r) => `${r.ok ? "✅" : "💥"} ${r.at.slice(5, 16).replace("T", " ")} UTC ${r.ok ? "" : r.note.slice(0, 80)}`).join("\n");
    const fix = heal[id]?.last_fix ? `\n🩹 last self-fix: ${heal[id].last_fix}` : "";
    return `• ${id}\n${last || "no runs yet"}${fix}`;
  });
  return say(env, out.join("\n\n") || "No runs yet.");
}

async function statusMsg(env) {
  const s = await status(env);
  const healed = Object.values(s.heal).filter((h) => h && h.last_fix).length;
  return say(env, `⚒ NIXFORGE v${s.version}\n🟢 ${s.workflows.filter((w) => w.status === "active").length} active · ⏸ ${s.workflows.filter((w) => w.status === "paused").length} paused\n🩹 ${healed} workflow(s) have healed themselves\n🧬 ${s.pitches} evolution pitch(es) waiting\n\n${SIGN}`);
}

async function status(env) {
  const [workflows, runs, heal, evo, version] = await Promise.all([
    listWorkflows(env), raw(env, "state/_runs.json"), raw(env, "state/_heal.json"), raw(env, "state/_evolution.json"), raw(env, "VERSION"),
  ]);
  const book = JSON.parse(evo || '{"items":{}}');
  return { maker: "Swanix 🐸", version: (version || "0.1").trim(), workflows, runs: JSON.parse(runs || "{}"), heal: JSON.parse(heal || "{}"),
    pitches: Object.values(book.items).filter((p) => p.status === "pitched").length, evolution: book.items };
}

async function listWorkflows(env) {
  const r = await gh(env, `/repos/${env.GH_REPO}/contents/workflows`);
  if (!r.ok) return [];
  const dirs = (await r.json()).filter((d) => d.type === "dir");
  return Promise.all(dirs.map(async (d) => {
    const y = (await raw(env, `workflows/${d.name}/spec.yaml`)) || "";
    const pick = (k) => (y.match(new RegExp(`^${k}:\\s*['"]?([^'"\\n]+)`, "m")) || [])[1] || null;
    return { id: d.name, title: pick("title"), status: pick("status") || "active", schedule: pick("schedule") };
  }));
}

// ── github ───────────────────────────────────────────────────
const gh = (env, path, init = {}) => fetch(GH + path, { ...init, headers: { authorization: `Bearer ${env.GH_TOKEN}`, accept: "application/vnd.github+json", "user-agent": "nixforge-by-swanix", ...(init.headers || {}) } });
async function dispatch(env, file, inputs) {
  const r = await gh(env, `/repos/${env.GH_REPO}/actions/workflows/${file}/dispatches`, { method: "POST", body: JSON.stringify({ ref: "main", inputs }) });
  if (!r.ok) throw new Error(`GitHub dispatch ${file} failed: ${r.status} ${await r.text()}`);
}
async function raw(env, path) {
  const r = await gh(env, `/repos/${env.GH_REPO}/contents/${path}`, { headers: { accept: "application/vnd.github.raw+json" } });
  return r.ok ? r.text() : null;
}
async function ghGet(env, path) {
  const r = await gh(env, `/repos/${env.GH_REPO}/contents/${path}`);
  if (!r.ok) throw new Error(`can't find ${path}`);
  const j = await r.json();
  return { sha: j.sha, text: new TextDecoder().decode(Uint8Array.from(atob(j.content.replace(/\n/g, "")), (c) => c.charCodeAt(0))) };
}
async function ghPut(env, path, text, message, sha) {
  const bytes = new TextEncoder().encode(text);
  let bin = ""; bytes.forEach((b) => (bin += String.fromCharCode(b)));
  const r = await gh(env, `/repos/${env.GH_REPO}/contents/${path}`, { method: "PUT", body: JSON.stringify({ message: `${message}\n\nForged-by: Swanix <nixforge>`, content: btoa(bin), sha }) });
  if (!r.ok) throw new Error(`save ${path} failed: ${r.status}`);
}
async function ghDelete(env, path, message) {
  const f = await ghGet(env, path);
  await gh(env, `/repos/${env.GH_REPO}/contents/${path}`, { method: "DELETE", body: JSON.stringify({ message, sha: f.sha }) });
}
const json = (o) => new Response(JSON.stringify(o), { headers: { "content-type": "application/json", "access-control-allow-origin": "*" } });

const HELP = `⚒ NIXFORGE — at your service, Swanix.

Just tell me what you want automated, in plain words. Or:
/new <task> — forge a new workflow
/list — your workflows
/run <id> — run one now
/pause <id> · /resume <id>
/logs [id] — recent runs and self-fixes
/convert <link> <mp3|mp4|wav|gif…>
/status — forge health
/evolve — self-review for upgrades

I fix my own errors quietly. I'll only ask you before I evolve.

${SIGN}`;

const DASHBOARD = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NIXFORGE · forged by Swanix</title><style>
:root{--bg:#07080d;--card:#10131c;--ink:#e8ecf4;--dim:#8a93a6;--cy:#22e1ff;--mg:#ff3df2;--ok:#3dff8a;--bad:#ff5d5d}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(1200px 600px at 20% -10%,#1b1440,transparent),var(--bg);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,sans-serif;padding:24px}
h1{margin:0;font-size:28px;letter-spacing:.08em;background:linear-gradient(90deg,var(--cy),var(--mg));-webkit-background-clip:text;color:transparent}
.sub{color:var(--dim);margin:4px 0 22px}.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(280px,1fr))}
.card{background:var(--card);border:1px solid #1f2533;border-radius:14px;padding:16px}.k{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.1em}
.big{font-size:30px;font-weight:700}.wf{display:flex;justify-content:space-between;gap:8px;align-items:center}.pill{font-size:12px;padding:2px 8px;border-radius:99px;background:#1a2030}
.dots{display:flex;gap:4px;margin-top:8px}.dot{width:10px;height:10px;border-radius:3px;background:#263044}.dot.ok{background:var(--ok)}.dot.bad{background:var(--bad)}
.fix{color:var(--cy);font-size:13px;margin-top:6px}footer{margin-top:28px;color:var(--dim);font-size:13px}</style></head><body>
<h1>⚒ NIXFORGE</h1><div class="sub">describe it. forge it. it heals. — <b>forged by Swanix 🐸</b></div>
<div class="grid" id="stats"></div><h3>Workflows</h3><div class="grid" id="wfs"></div>
<footer>Self-heals quietly · evolves only with Swanix's approval · runs free on GitHub Actions + Cloudflare</footer>
<script>
fetch('/api/status').then(r=>r.json()).then(s=>{
 const act=s.workflows.filter(w=>w.status==='active').length, heals=Object.values(s.heal).filter(h=>h&&h.last_fix).length;
 stats.innerHTML=[['version','v'+s.version],['active',act],['self-heals',heals],['evolution pitches',s.pitches]].map(([k,v])=>'<div class="card"><div class="k">'+k+'</div><div class="big">'+v+'</div></div>').join('');
 wfs.innerHTML=s.workflows.map(w=>{const r=(s.runs[w.id]||[]).slice(0,12);const h=s.heal[w.id]||{};
  return '<div class="card"><div class="wf"><b>'+w.id+'</b><span class="pill">'+w.status+'</span></div><div class="k">'+(w.schedule?'⏰ '+w.schedule:'▶️ on demand')+'</div><div class="dots">'+r.map(x=>'<span class="dot '+(x.ok?'ok':'bad')+'" title="'+x.at+'"></span>').join('')+'</div>'+(h.last_fix?'<div class="fix">🩹 '+h.last_fix+'</div>':'')+'</div>'}).join('');
});</script></body></html>`;
