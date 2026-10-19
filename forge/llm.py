# ─────────────────────────────────────────────────────────────
#  ⚒  NIXFORGE · llm.py — three free brains, one voice
#  forged by Swanix 🐸  ·  Gemini → Groq → OpenRouter, never a card
# ─────────────────────────────────────────────────────────────
import json
import os
import re
import time

import requests

from .sig import log

TIMEOUT = 60


def _gemini(prompt: str, system: str) -> str:
    key = os.environ["GEMINI_API_KEY"]
    models = [m for m in (os.environ.get("GEMINI_MODEL"), "gemini-2.5-flash",
                          "gemini-flash-latest", "gemini-2.5-flash-lite") if m]
    last = ""
    for model in dict.fromkeys(models):  # v0.4.1: Google retires models; walk the list
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": key},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2},
            },
            timeout=TIMEOUT,
        )
        if r.status_code == 404:
            last = f"{model} 404"
            continue
        if not r.ok:
            raise RuntimeError(f"{model} {r.status_code}: {r.text[:200]}")
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    raise RuntimeError(f"no live gemini model ({last})")


def _openai_style(url: str, key: str, model: str, prompt: str, system: str, fallbacks: tuple = ()) -> str:
    models = list(dict.fromkeys([model, *fallbacks]))
    json_mode = "ONE JSON object" in prompt
    last = ""
    for m in models:
        for strict in ([True, False] if json_mode else [False]):
            r = requests.post(
                url,
                headers={"Authorization": f"Bearer {key}", "X-Title": "NIXFORGE by Swanix"},
                json={
                    "model": m,
                    "temperature": 0.2,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                    **({"response_format": {"type": "json_object"}} if strict else {}),
                },
                timeout=TIMEOUT,
            )
            if r.ok:
                return r.json()["choices"][0]["message"]["content"]
            last = f"{m} {r.status_code}: {r.text[:200]}"
            if r.status_code in (401, 403, 429):
                raise RuntimeError(last)
    raise RuntimeError(last)


def _groq(prompt: str, system: str) -> str:
    return _openai_style(
        "https://api.groq.com/openai/v1/chat/completions",
        os.environ["GROQ_API_KEY"],
        os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
        prompt, system, ("openai/gpt-oss-20b", "llama-3.1-8b-instant"),
    )


def _openrouter(prompt: str, system: str) -> str:
    return _openai_style(
        "https://openrouter.ai/api/v1/chat/completions",
        os.environ["OPENROUTER_API_KEY"],
        os.environ.get("OPENROUTER_MODEL", "openai/gpt-oss-20b:free"),
        prompt, system, ("meta-llama/llama-3.3-70b-instruct:free",),
    )


CHAIN = [("gemini", "GEMINI_API_KEY", _gemini), ("groq", "GROQ_API_KEY", _groq),
         ("openrouter", "OPENROUTER_API_KEY", _openrouter)]


def chat(prompt: str, system: str = "You are NIXFORGE, a precise automation engineer.") -> str:
    """Ask the first free provider that answers. 2 tries each, then fall through."""
    errors = []
    for name, env, fn in CHAIN:
        if not os.environ.get(env):
            continue
        for attempt in range(2):
            try:
                out = fn(prompt, system)
                log(f"brain: {name} answered")
                return out
            except Exception as e:  # noqa: BLE001 — every brain may stumble
                errors.append(f"{name}#{attempt + 1}: {str(e)[:160]}")
                time.sleep(2 * (attempt + 1))
    raise RuntimeError("all free brains are down: " + " | ".join(errors or ["no API keys set"]))


def chat_long(prompt: str, system: str, max_tokens: int = 32000) -> tuple[str, bool]:
    """Big outputs (whole websites). Returns (text, finished). finished=False means cut off."""
    errors = []
    if os.environ.get("GEMINI_API_KEY"):
        for model in ("gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-flash-lite"):
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                    json={"systemInstruction": {"parts": [{"text": system}]},
                          "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                          "generationConfig": {"temperature": 0.4, "maxOutputTokens": max_tokens,
                                               "thinkingConfig": {"thinkingBudget": 1024}}},
                    timeout=300)
                if not r.ok:
                    errors.append(f"gemini {model} {r.status_code}")
                    continue
                c = r.json()["candidates"][0]
                text = "".join(p.get("text", "") for p in c.get("content", {}).get("parts", []))
                if text:
                    log(f"brain(long): gemini {model} answered")
                    return text, c.get("finishReason") != "MAX_TOKENS"
            except Exception as e:  # noqa: BLE001
                errors.append(f"gemini {model}: {str(e)[:120]}")
    for url, env, models in (("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY",
                              ("openai/gpt-oss-120b", "openai/gpt-oss-20b")),
                             ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY",
                              ("openai/gpt-oss-20b:free",))):
        if not os.environ.get(env):
            continue
        for m in models:
            try:
                r = requests.post(url, headers={"Authorization": f"Bearer {os.environ[env]}"},
                                  json={"model": m, "temperature": 0.4, "max_tokens": max_tokens,
                                        "messages": [{"role": "system", "content": system},
                                                     {"role": "user", "content": prompt}]},
                                  timeout=300)
                if not r.ok:
                    errors.append(f"{m} {r.status_code}: {r.text[:100]}")
                    continue
                ch = r.json()["choices"][0]
                log(f"brain(long): {m} answered")
                return ch["message"]["content"] or "", ch.get("finish_reason") != "length"
            except Exception as e:  # noqa: BLE001
                errors.append(f"{m}: {str(e)[:120]}")
    raise RuntimeError("no brain could write a long answer: " + " | ".join(errors or ["no API keys set"]))


def chat_json(prompt: str, system: str) -> dict:
    """Ask for JSON and dig it out even when the model wraps it in prose/fences."""
    text = chat(prompt + "\n\nReply with ONE JSON object only. No prose, no code fences.", system)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"brain returned no JSON: {text[:200]}")
    raw = m.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # models love stray backslashes (regex, CSS escapes): double the invalid ones
        return json.loads(re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', raw))
