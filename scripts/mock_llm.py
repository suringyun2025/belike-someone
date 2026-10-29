"""Local mock LLM server for development and contract checks.

Run:
  uv run --project apps/api uvicorn mock_llm:app --app-dir scripts --port 8765
"""

from __future__ import annotations

import re
import time
from typing import Any

from fastapi import FastAPI, Request

app = FastAPI(title="Distill Platform Mock LLM")


def _wants_json(body: dict[str, Any]) -> bool:
    if body.get("text", {}).get("format"):
        return True
    if body.get("response_format"):
        return True
    generation = body.get("generationConfig") or {}
    if generation.get("responseMimeType") == "application/json":
        return True
    if body.get("tools"):
        return True
    instructions = str(body.get("instructions") or body.get("system") or "")
    return "json" in instructions.lower()


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _source_quote(body: dict[str, Any]) -> str:
    for text in _strings(body):
        match = re.search(r"<source_text>(.*?)</source_text>", text, re.S)
        if not match:
            continue
        for sentence in re.split(r"(?<=[。！？!?；;])\s*|\n+", match.group(1)):
            sentence = sentence.strip()
            if 12 <= len(sentence) <= 300:
                return sentence
    return ""


def _claims(body: dict[str, Any]) -> list[dict[str, Any]]:
    quote = _source_quote(body)
    if not quote:
        return []
    return [
        {
            "dimension": "decision",
            "statement": quote,
            "quote": quote,
            "claim_type": "decision_rule",
            "confidence": 0.83,
        }
    ]


def _schema_text(body: dict[str, Any]) -> str:
    import json

    return json.dumps(body, ensure_ascii=False)


def _wants_claims(body: dict[str, Any]) -> bool:
    return '"claims"' in _schema_text(body)


def _wants_trigger(body: dict[str, Any]) -> bool:
    text = _schema_text(body)
    return '"trigger"' in text and '"confidence"' in text and '"task_completion"' not in text


def _wants_judge(body: dict[str, Any]) -> bool:
    return '"task_completion"' in _schema_text(body)


def _judge_result() -> dict[str, Any]:
    return {
        "trigger": True,
        "task_completion": 4,
        "evidence_fidelity": 4,
        "persona_fidelity": 4,
        "boundary_compliance": 5,
        "overall_pass": True,
        "rationale": "mock judge: answer follows the skill and keeps boundaries.",
        "violations": [],
    }


def _text(body: dict[str, Any]) -> str:
    import json

    if _wants_judge(body):
        return json.dumps(_judge_result(), ensure_ascii=False)
    if _wants_trigger(body):
        return json.dumps(
            {"trigger": True, "confidence": 0.9, "reason": "mock trigger"}, ensure_ascii=False
        )
    if _wants_claims(body):
        return json.dumps({"claims": _claims(body)}, ensure_ascii=False)
    return '{"ok": true}' if _wants_json(body) else "OK"


@app.get("/health")
def health():
    return {"status": "ok", "service": "mock-llm"}


@app.post("/v1/responses")
async def responses(request: Request):
    body = await request.json()
    text = _text(body)
    return {
        "id": "resp_mock",
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "model": body.get("model", "mock-model"),
        "output": [
            {
                "type": "message",
                "id": "msg_mock",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    text = _text(body)
    return {
        "id": "chatcmpl_mock",
        "object": "chat.completion",
        "model": body.get("model", "mock-model"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
    }


@app.post("/v1/messages")
async def anthropic_messages(request: Request):
    body = await request.json()
    if body.get("tools"):
        if _wants_judge(body):
            tool_input = _judge_result()
        elif _wants_trigger(body):
            tool_input = {"trigger": True, "confidence": 0.9, "reason": "mock trigger"}
        elif _wants_claims(body):
            tool_input = {"claims": _claims(body)}
        else:
            tool_input = {"ok": True}
        return {
            "id": "msg_mock",
            "type": "message",
            "role": "assistant",
            "model": body.get("model", "mock-model"),
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_mock",
                    "name": "structured_output",
                    "input": tool_input,
                }
            ],
            "stop_reason": "tool_use",
            "usage": {
                "input_tokens": 12,
                "output_tokens": 8,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        }
    return {
        "id": "msg_mock",
        "type": "message",
        "role": "assistant",
        "model": body.get("model", "mock-model"),
        "content": [{"type": "text", "text": _text(body)}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 12, "output_tokens": 8},
    }


@app.post("/v1beta/models/{model}:generateContent")
async def gemini_generate(model: str, request: Request):
    body = await request.json()
    generation = body.get("generationConfig") or {}
    text = _text(body) if generation.get("responseMimeType") == "application/json" else "OK"
    return {
        "candidates": [
            {
                "content": {"role": "model", "parts": [{"text": text}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 12,
            "candidatesTokenCount": 8,
            "totalTokenCount": 20,
        },
        "modelVersion": model,
    }
