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
    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
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
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _openai_style(url: str, key: str, model: str, prompt: str, system: str) -> str:
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}", "X-Title": "NIXFORGE by Swanix"},
        json={
            "model": model,
            "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            **({"response_format": {"type": "json_object"}} if "ONE JSON object" in prompt else {}),
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _groq(prompt: str, system: str) -> str:
    return _openai_style(
        "https://api.groq.com/openai/v1/chat/completions",
        os.environ["GROQ_API_KEY"],
        os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
        prompt, system,
    )


def _openrouter(prompt: str, system: str) -> str:
    return _openai_style(
        "https://openrouter.ai/api/v1/chat/completions",
        os.environ["OPENROUTER_API_KEY"],
        os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
        prompt, system,
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
