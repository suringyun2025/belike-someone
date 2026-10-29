from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.llm import (
    AnthropicMessagesAdapter,
    GeminiGenerateContentAdapter,
    LLMError,
    LLMMessage,
    LLMRequest,
    OpenAIChatAdapter,
    OpenAIResponsesAdapter,
)
from app.models import Provider


def _provider(protocol: str, base_url: str, model_id: str = "mock-model") -> Provider:
    return Provider(
        name="mock",
        protocol=protocol,
        base_url=base_url,
        model_id=model_id,
        api_key_encrypted="",
        params={},
    )


def _request(json_schema: dict | None = None) -> LLMRequest:
    return LLMRequest(
        system="test system",
        messages=[LLMMessage("user", "hello")],
        max_output_tokens=128,
        json_schema=json_schema,
    )


@respx.mock
def test_openai_responses_adapter():
    route = respx.post("https://mock.test/v1/responses").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "resp_1",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "hello back"}],
                    }
                ],
                "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
            },
        )
    )
    response = OpenAIResponsesAdapter(_provider("openai_responses", "https://mock.test/v1")).generate(_request())
    assert response.text == "hello back"
    assert route.called
    payload = json.loads(route.calls[0].request.content)
    assert payload["store"] is False
    assert payload["instructions"] == "test system"


@respx.mock
def test_openai_chat_adapter_and_json():
    route = respx.post("https://mock.test/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chat_1",
                "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        )
    )
    response = OpenAIChatAdapter(_provider("openai_chat", "https://mock.test/v1")).generate(
        _request({"type": "object", "properties": {"ok": {"type": "boolean"}}})
    )
    assert response.json_data == {"ok": True}
    payload = json.loads(route.calls[0].request.content)
    assert payload["response_format"]["type"] == "json_schema"


@respx.mock
def test_anthropic_adapter_uses_tool_for_json():
    route = respx.post("https://mock.test/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "content": [
                    {"type": "tool_use", "id": "tool_1", "name": "structured_output", "input": {"ok": True}}
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 3, "output_tokens": 2},
            },
        )
    )
    response = AnthropicMessagesAdapter(_provider("anthropic", "https://mock.test/v1")).generate(
        _request({"type": "object", "properties": {"ok": {"type": "boolean"}}})
    )
    assert response.json_data == {"ok": True}
    payload = json.loads(route.calls[0].request.content)
    assert payload["tool_choice"]["type"] == "tool"
    assert payload["max_tokens"] == 128


@respx.mock
def test_gemini_adapter_and_generation_config():
    route = respx.post("https://mock.test/v1beta/models/mock-model:generateContent").mock(
        return_value=httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": '{"ok": true}'}]}, "finishReason": "STOP"}
                ],
                "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2, "totalTokenCount": 5},
            },
        )
    )
    response = GeminiGenerateContentAdapter(_provider("gemini", "https://mock.test/v1beta")).generate(
        _request({"type": "object", "properties": {"ok": {"type": "boolean"}}})
    )
    assert response.json_data == {"ok": True}
    payload = json.loads(route.calls[0].request.content)
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert "responseSchema" in payload["generationConfig"]
    assert "additionalProperties" not in json.dumps(payload["generationConfig"]["responseSchema"])


@respx.mock
def test_error_mapping_auth():
    respx.post("https://mock.test/v1/responses").mock(
        return_value=httpx.Response(401, json={"error": {"message": "bad key"}})
    )
    with pytest.raises(LLMError) as exc:
        OpenAIResponsesAdapter(_provider("openai_responses", "https://mock.test/v1")).generate(_request())
    assert exc.value.code == "AUTH_ERROR"
