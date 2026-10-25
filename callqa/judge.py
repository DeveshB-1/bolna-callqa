"""A small LLM-as-judge over a Bolna transcript, for things a counter can't see.

Each rubric item names a failure. The judge answers true when the failure
happened, which matches the human label convention in agreement.py, so judge
verdicts can be scored against annotators with ``callqa agree``.

Works with any OpenAI-compatible endpoint (OpenAI, Groq, OpenRouter, Ollama):
JUDGE_BASE_URL, JUDGE_API_KEY, JUDGE_MODEL.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Callable

RUBRIC = {
    "language_mismatch": "The agent replied in a different language or script than the caller was using "
                         "(for example English replies to a caller speaking Hindi or Hinglish).",
    "ignored_question": "The caller asked something and the agent never answered it or gave a next step.",
    "restarted_after_interrupt": "After the caller cut in, the agent went back to its script instead of "
                                 "responding to what the caller said.",
}

ChatFn = Callable[[list[dict]], str]


def transcript_text(bundle: dict) -> str:
    lines = []
    for i, row in enumerate((bundle.get("progression") or {}).get("transcript") or []):
        if row.get("kind") == "message":
            cut = " [interrupted]" if row.get("interrupted") else ""
            lines.append(f"[{i}] {row.get('role')}: {row.get('text', '')}{cut}")
        elif row.get("kind") == "function_call":
            lines.append(f"[{i}] tool {row.get('tool_name')} -> {row.get('status')}")
        elif row.get("kind") == "event":
            lines.append(f"[{i}] event: {row.get('label')}")
    return "\n".join(lines)


def build_messages(bundle: dict, rubric: dict[str, str] = RUBRIC) -> list[dict]:
    items = "\n".join(f"- {k}: {v}" for k, v in rubric.items())
    return [
        {"role": "system", "content": (
            "You grade voice agent calls. For each rubric item answer true only if the failure "
            "clearly happened in the transcript. Reply with JSON only: "
            '{"<item>": {"verdict": true|false, "reason": "<one sentence>"}}')},
        {"role": "user", "content": f"Rubric:\n{items}\n\nTranscript:\n{transcript_text(bundle)}"},
    ]


def parse_verdicts(text: str, rubric: dict[str, str] = RUBRIC) -> dict[str, dict]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"judge returned no JSON: {text[:120]!r}")
    raw = json.loads(m.group(0))
    out = {}
    for item in rubric:
        v = raw.get(item)
        if isinstance(v, dict):
            out[item] = {"verdict": bool(v.get("verdict")), "reason": str(v.get("reason", ""))}
        elif isinstance(v, bool):
            out[item] = {"verdict": v, "reason": ""}
    missing = set(rubric) - set(out)
    if missing:
        raise ValueError(f"judge skipped items: {sorted(missing)}")
    return out


def openai_compatible_chat(base_url: str | None = None, api_key: str | None = None,
                           model: str | None = None) -> ChatFn:
    base = (base_url or os.environ.get("JUDGE_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    key = api_key or os.environ.get("JUDGE_API_KEY", "")
    mdl = model or os.environ.get("JUDGE_MODEL", "gpt-4o-mini")

    def chat(messages: list[dict]) -> str:
        body = json.dumps({"model": mdl, "messages": messages, "temperature": 0}).encode()
        req = urllib.request.Request(f"{base}/chat/completions", data=body, method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            return json.loads(resp.read())["choices"][0]["message"]["content"]

    return chat


def judge_call(bundle: dict, chat: ChatFn, rubric: dict[str, str] = RUBRIC) -> dict[str, dict]:
    return parse_verdicts(chat(build_messages(bundle, rubric)), rubric)
