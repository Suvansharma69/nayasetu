r"""The one generation path: local Ollama over its REST API.

CLAUDE.md Section 2: generation is fully local and there is no cloud path --
nothing about a case leaves this machine. No LLM SDK either (requirements.txt):
Ollama's /api/chat is one POST, and httpx is already in the environment.

Settings that matter
--------------------
* `format` = a JSON schema: Ollama constrains decoding to it, so a reply always
  parses. It does NOT make the content true -- qwen3.5:4b, asked what BNS 303
  covers, confidently described a bomb-threat offence. That is Node 2's job.
* `think: false`: qwen3.5 is a thinking model, and on this machine it runs
  ~half on CPU, so hidden reasoning tokens would multiply the latency.
* temperature 0 + a fixed seed: the same case should give the same proposals,
  which is what makes "routes correctly every time" testable at all.
"""
from __future__ import annotations

import json
import os

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen3.5:4b"
TIMEOUT_S = float(os.environ.get("OLLAMA_TIMEOUT", "600"))


class LLMError(RuntimeError):
    pass


def host():
    return os.environ.get("OLLAMA_HOST", DEFAULT_HOST).rstrip("/")


def model():
    return os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL).strip()


def context_size(messages, num_predict):
    """Smallest of 8K/16K/32K that holds the prompt plus the reply.

    A lawyer's brief fits 8K; IL-TUR LSI facts average ~2,400 words and do not.
    Ollama silently TRUNCATES a prompt longer than num_ctx -- the model would
    then judge facts it never saw -- so the size follows the prompt. Estimated
    at ~3 characters per token, deliberately pessimistic for legal English.
    """
    need = sum(len(m["content"]) for m in messages) // 3 + num_predict + 256
    for size in (8192, 16384, 32768):
        if need <= size:
            return size
    raise LLMError(f"prompt needs ~{need} tokens, over the 32K this machine can hold")


def chat_json(messages, schema, model_name=None, num_ctx=None, num_predict=1024):
    """Send `messages`, return the reply parsed as JSON conforming to `schema`."""
    import httpx

    num_ctx = num_ctx or context_size(messages, num_predict)
    body = {
        "model": model_name or model(),
        "messages": messages,
        "format": schema,
        "stream": False,
        "think": False,
        # num_predict is a backstop: the schema's own bounds should end the
        # reply well before it (see nodes.PROPOSAL_SCHEMA).
        "options": {"temperature": 0, "seed": 0, "num_ctx": num_ctx, "num_predict": num_predict},
    }
    try:
        r = httpx.post(f"{host()}/api/chat", json=body, timeout=TIMEOUT_S)
    except httpx.ConnectError as e:
        raise LLMError(f"Ollama is not reachable at {host()} -- is the service running? ({e})") from e
    if r.status_code != 200:
        raise LLMError(f"Ollama returned {r.status_code}: {r.text[:300]}")
    data = r.json()
    content = data.get("message", {}).get("content", "")
    if data.get("done_reason") == "length":
        raise LLMError(f"Ollama reply hit the {num_predict}-token cap before the JSON closed")
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise LLMError(f"Ollama reply is not JSON despite the schema: {content[:300]!r}") from e
