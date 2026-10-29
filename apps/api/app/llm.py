from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import settings
from .models import Provider
from .security import decrypt_secret

DEFAULT_MAX_TOKENS = 4096
VERSION_SEGMENT = re.compile(r"^v\d+[a-z0-9]*$", re.I)


class LLMError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status: int | None = None,
        retryable: bool = False,
        request_id: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable
        self.request_id = request_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "status": self.status,
            "retryable": self.retryable,
            "request_id": self.request_id,
        }


@dataclass
class LLMMessage:
    role: str
    content: str


@dataclass
class LLMRequest:
    system: str = ""
    messages: list[LLMMessage] = field(default_factory=list)
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int = DEFAULT_MAX_TOKENS
    json_schema: dict[str, Any] | None = None
    json_mode: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    text: str
    json_data: dict[str, Any] | list[Any] | None = None
    finish_reason: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""
    warnings: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


def _normalized_base(base_url: str, default_version: str = "v1") -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return ""
    parsed = urlparse(base)
    segments = [segment for segment in parsed.path.split("/") if segment]
    if segments and VERSION_SEGMENT.match(segments[-1]):
        return base
    return f"{base}/{default_version}"


def _request_id(response: httpx.Response, body: dict[str, Any] | None = None) -> str:
    for header in ("x-request-id", "request-id", "x-goog-request-id", "cf-ray"):
        if value := response.headers.get(header):
            return value
    if body and isinstance(body.get("id"), str):
        return body["id"]
    return ""


def _map_error(response: httpx.Response, body: dict[str, Any] | None = None) -> LLMError:
    status = response.status_code
    detail = ""
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            detail = str(error.get("message") or error.get("type") or "")
        elif isinstance(error, str):
            detail = error
        if not detail:
            detail = str(body.get("message") or body.get("detail") or "")
    detail = detail or response.text[:500]
    lowered = detail.lower()
    if status == 401:
        code, retryable = "AUTH_ERROR", False
    elif status == 403:
        code, retryable = "PERMISSION_ERROR", False
    elif status == 404:
        code, retryable = "MODEL_NOT_FOUND", False
    elif status == 429:
        code, retryable = ("QUOTA_EXCEEDED" if "quota" in lowered else "RATE_LIMITED"), True
    elif status == 408:
        code, retryable = "TIMEOUT", True
    elif status >= 500:
        code, retryable = "PROVIDER_ERROR", True
    elif status == 400:
        code = "CONTEXT_LENGTH" if "context" in lowered and ("length" in lowered or "token" in lowered) else "INVALID_REQUEST"
        retryable = False
    else:
        code, retryable = "PROVIDER_ERROR", False
    return LLMError(code, detail or f"HTTP {status}", status, retryable, _request_id(response, body))


def _loads_json(text: str) -> Any:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    return json.loads(value)


def _base_headers(key: str) -> dict[str, str]:
    headers = {"content-type": "application/json", "accept": "application/json"}
    if key:
        headers["authorization"] = f"Bearer {key}"
    return headers


class BaseAdapter:
    protocol = "base"

    def __init__(self, provider: Provider, owner_id: str = "") -> None:
        self.provider = provider
        # The owner id is required to unseal keys written by the multiuser build.
        # Leaving it empty still works for legacy single-user rows.
        self.api_key = decrypt_secret(
            provider.api_key_encrypted, owner_id or (provider.owner_id or "")
        )
        self.params: dict[str, Any] = provider.params or {}

    def _headers(self) -> dict[str, str]:
        headers = _base_headers(self.api_key)
        custom = self.params.get("extra_headers") or {}
        if isinstance(custom, dict):
            headers.update({str(k): str(v) for k, v in custom.items()})
        return headers

    def _merge_extra(self, payload: dict[str, Any]) -> dict[str, Any]:
        extra = self.params.get("extra_body") or {}
        if isinstance(extra, dict):
            payload.update(extra)
        return payload

    def generate(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError

    def test_connection(self, json_mode: bool = False) -> dict[str, Any]:
        started = time.perf_counter()
        request = LLMRequest(
            system="You are a connectivity probe.",
            messages=[LLMMessage("user", "只回复 OK")],
            max_output_tokens=32,
            json_mode=json_mode,
            json_schema=(
                {
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                    "additionalProperties": False,
                }
                if json_mode
                else None
            ),
        )
        try:
            response = self.generate(request)
            return {
                "ok": True,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "text": response.text[:200],
                "model": self.provider.model_id,
                "warnings": response.warnings,
                "error_code": "",
                "error_message": "",
            }
        except LLMError as exc:
            return {
                "ok": False,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "text": "",
                "model": self.provider.model_id,
                "warnings": [],
                "error_code": exc.code,
                "error_message": exc.message,
            }
        except Exception as exc:  # pragma: no cover - network boundary
            return {
                "ok": False,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "text": "",
                "model": self.provider.model_id,
                "warnings": [],
                "error_code": "NETWORK_ERROR",
                "error_message": str(exc),
            }

    def _post(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> tuple[dict[str, Any], httpx.Response]:
        try:
            with httpx.Client(timeout=settings.http_timeout_seconds) as client:
                response = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMError("TIMEOUT", f"请求超时：{exc}", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LLMError("NETWORK_ERROR", f"网络错误：{exc}", retryable=True) from exc
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code >= 400:
            raise _map_error(response, body if isinstance(body, dict) else None)
        if not isinstance(body, dict):
            raise LLMError(
                "INVALID_RESPONSE",
                "供应商返回了非 JSON 响应",
                response.status_code,
                False,
                _request_id(response),
            )
        return body, response

    def _finish_error(self, finish_reason: str, request_id: str) -> None:
        reason = (finish_reason or "").lower()
        if reason in {"content_filter", "safety", "recitation", "blocked", "refusal"}:
            raise LLMError(
                "CONTENT_FILTERED",
                "供应商内容安全策略拦截了本次生成",
                request_id=request_id,
            )

    def _structured_payload(self, request: LLMRequest) -> tuple[dict[str, Any] | None, bool]:
        if request.json_schema:
            return request.json_schema, True
        if request.json_mode:
            return None, True
        return None, False


class OpenAIResponsesAdapter(BaseAdapter):
    protocol = "openai_responses"

    def generate(self, request: LLMRequest) -> LLMResponse:
        base = _normalized_base(self.provider.base_url or "https://api.openai.com/v1", "v1")
        url = f"{base}/responses"
        input_items = [
            {"role": "user" if message.role == "user" else "assistant", "content": message.content}
            for message in request.messages
        ]
        payload: dict[str, Any] = {
            "model": self.provider.model_id,
            "input": input_items,
            "store": False,
            "stream": False,
        }
        if request.system:
            payload["instructions"] = request.system
        max_tokens = request.max_output_tokens or self.params.get("max_output_tokens") or DEFAULT_MAX_TOKENS
        payload["max_output_tokens"] = max_tokens
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        schema, wants_json = self._structured_payload(request)
        if schema:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "structured_output",
                    "schema": schema,
                    "strict": True,
                }
            }
        elif wants_json:
            payload["instructions"] = (payload.get("instructions", "") + "\n只输出合法 JSON，不要 Markdown 代码围栏。").strip()
        if reasoning := self.params.get("reasoning"):
            payload["reasoning"] = reasoning
        if truncation := self.params.get("truncation"):
            payload["truncation"] = truncation
        headers = self._headers()
        body, response = self._post(url, self._merge_extra(payload), headers)
        if body.get("status") == "failed":
            error = body.get("error") or {}
            raise LLMError(
                "PROVIDER_ERROR",
                str(error.get("message") or "Responses API 返回 failed"),
                response.status_code,
                False,
                _request_id(response, body),
            )
        output_text = body.get("output_text")
        if not isinstance(output_text, str):
            parts: list[str] = []
            for item in body.get("output") or []:
                if not isinstance(item, dict):
                    continue
                for content in item.get("content") or []:
                    if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                        parts.append(str(content.get("text") or ""))
            output_text = "".join(parts)
        usage = body.get("usage") or {}
        normalized_usage = {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }
        request_id = _request_id(response, body)
        finish_reason = body.get("status") or ""
        if body.get("incomplete_details"):
            finish_reason = str(body["incomplete_details"])
        self._finish_error(finish_reason, request_id)
        json_data = None
        if wants_json:
            try:
                json_data = _loads_json(output_text)
            except (ValueError, TypeError) as exc:
                raise LLMError("INVALID_RESPONSE", "模型没有返回合法 JSON", request_id=request_id) from exc
        return LLMResponse(
            text=output_text,
            json_data=json_data,
            finish_reason=finish_reason,
            usage=normalized_usage,
            request_id=request_id,
            raw=body,
        )


class OpenAIChatAdapter(BaseAdapter):
    protocol = "openai_chat"

    def generate(self, request: LLMRequest) -> LLMResponse:
        base = _normalized_base(self.provider.base_url or "https://api.openai.com/v1", "v1")
        url = f"{base}/chat/completions"
        messages: list[dict[str, Any]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.extend({"role": m.role, "content": m.content} for m in request.messages)
        payload: dict[str, Any] = {
            "model": self.provider.model_id,
            "messages": messages,
            "stream": False,
        }
        max_tokens = request.max_output_tokens or self.params.get("max_output_tokens") or DEFAULT_MAX_TOKENS
        payload["max_tokens"] = max_tokens
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        schema, wants_json = self._structured_payload(request)
        if schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "structured_output", "schema": schema, "strict": True},
            }
        elif wants_json:
            payload["response_format"] = {"type": "json_object"}
        headers = self._headers()
        body, response = self._post(url, self._merge_extra(payload), headers)
        choices = body.get("choices") or []
        if not choices:
            raise LLMError("INVALID_RESPONSE", "Chat Completions 响应中没有 choices", request_id=_request_id(response, body))
        choice = choices[0] or {}
        message = choice.get("message") or {}
        output_text = message.get("content") or ""
        if isinstance(output_text, list):
            output_text = "".join(
                str(part.get("text") or "") for part in output_text if isinstance(part, dict)
            )
        usage = body.get("usage") or {}
        normalized_usage = {
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }
        request_id = _request_id(response, body)
        finish_reason = str(choice.get("finish_reason") or "")
        self._finish_error(finish_reason, request_id)
        json_data = None
        if wants_json:
            try:
                json_data = _loads_json(str(output_text))
            except (ValueError, TypeError) as exc:
                raise LLMError("INVALID_RESPONSE", "模型没有返回合法 JSON", request_id=request_id) from exc
        return LLMResponse(
            text=str(output_text),
            json_data=json_data,
            finish_reason=finish_reason,
            usage=normalized_usage,
            request_id=request_id,
            raw=body,
        )


class AnthropicMessagesAdapter(BaseAdapter):
    protocol = "anthropic"

    def _headers(self) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "accept": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": self.provider.api_version or "2023-06-01",
        }
        custom = self.params.get("extra_headers") or {}
        if isinstance(custom, dict):
            headers.update({str(k): str(v) for k, v in custom.items()})
        return headers

    def generate(self, request: LLMRequest) -> LLMResponse:
        base = _normalized_base(self.provider.base_url or "https://api.anthropic.com/v1", "v1")
        url = f"{base}/messages"
        messages = [
            {"role": message.role, "content": [{"type": "text", "text": message.content}]}
            for message in request.messages
        ]
        payload: dict[str, Any] = {
            "model": self.provider.model_id,
            "max_tokens": request.max_output_tokens or self.params.get("max_output_tokens") or DEFAULT_MAX_TOKENS,
            "messages": messages,
            "stream": False,
        }
        if request.system:
            payload["system"] = request.system
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if self.params.get("top_k") is not None:
            payload["top_k"] = self.params["top_k"]
        if self.params.get("stop_sequences"):
            payload["stop_sequences"] = self.params["stop_sequences"]
        schema, wants_json = self._structured_payload(request)
        if schema:
            payload["tools"] = [
                {
                    "name": "structured_output",
                    "description": "Return the structured result in the requested schema.",
                    "input_schema": schema,
                }
            ]
            payload["tool_choice"] = {"type": "tool", "name": "structured_output"}
        elif wants_json:
            payload["system"] = (payload.get("system", "") + "\n只输出合法 JSON，不要 Markdown 代码围栏。").strip()
        headers = self._headers()
        body, response = self._post(url, self._merge_extra(payload), headers)
        text_parts: list[str] = []
        json_data: Any = None
        for block in body.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text_parts.append(str(block.get("text") or ""))
            elif block.get("type") == "tool_use" and isinstance(block.get("input"), (dict, list)):
                json_data = block["input"]
        output_text = "".join(text_parts)
        usage = body.get("usage") or {}
        normalized_usage = {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
        }
        request_id = _request_id(response, body)
        stop_reason = str(body.get("stop_reason") or "")
        self._finish_error(stop_reason, request_id)
        if wants_json and json_data is None:
            try:
                json_data = _loads_json(output_text)
            except (ValueError, TypeError) as exc:
                raise LLMError("INVALID_RESPONSE", "模型没有返回合法 JSON", request_id=request_id) from exc
        return LLMResponse(
            text=output_text or (json.dumps(json_data, ensure_ascii=False) if json_data is not None else ""),
            json_data=json_data,
            finish_reason=stop_reason,
            usage=normalized_usage,
            request_id=request_id,
            raw=body,
        )


def _gemini_schema(value: Any) -> Any:
    """Keep the OpenAPI subset Gemini accepts; drop JSON-Schema-only keywords."""
    if isinstance(value, dict):
        return {
            key: _gemini_schema(item)
            for key, item in value.items()
            if key not in {"additionalProperties", "$schema", "strict", "$id", "$defs"}
        }
    if isinstance(value, list):
        return [_gemini_schema(item) for item in value]
    return value


class GeminiGenerateContentAdapter(BaseAdapter):
    protocol = "gemini"

    def _headers(self) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "accept": "application/json",
            "x-goog-api-key": self.api_key,
        }
        custom = self.params.get("extra_headers") or {}
        if isinstance(custom, dict):
            headers.update({str(k): str(v) for k, v in custom.items()})
        return headers

    def generate(self, request: LLMRequest) -> LLMResponse:
        base = _normalized_base(
            self.provider.base_url or "https://generativelanguage.googleapis.com/v1beta",
            "v1beta",
        )
        model = self.provider.model_id.removeprefix("models/")
        url = f"{base}/models/{model}:generateContent"
        contents = [
            {
                "role": "user" if message.role == "user" else "model",
                "parts": [{"text": message.content}],
            }
            for message in request.messages
        ]
        payload: dict[str, Any] = {"contents": contents}
        if request.system:
            payload["systemInstruction"] = {"parts": [{"text": request.system}]}
        generation: dict[str, Any] = {
            "maxOutputTokens": request.max_output_tokens
            or self.params.get("max_output_tokens")
            or DEFAULT_MAX_TOKENS
        }
        if request.temperature is not None:
            generation["temperature"] = request.temperature
        if request.top_p is not None:
            generation["topP"] = request.top_p
        if self.params.get("top_k") is not None:
            generation["topK"] = self.params["top_k"]
        if self.params.get("stop_sequences"):
            generation["stopSequences"] = self.params["stop_sequences"]
        schema, wants_json = self._structured_payload(request)
        if wants_json:
            generation["responseMimeType"] = "application/json"
        if schema:
            generation["responseSchema"] = _gemini_schema(schema)
        payload["generationConfig"] = generation
        if self.params.get("safety_settings"):
            payload["safetySettings"] = self.params["safety_settings"]
        headers = self._headers()
        body, response = self._post(url, self._merge_extra(payload), headers)
        candidates = body.get("candidates") or []
        if not candidates:
            feedback = body.get("promptFeedback") or {}
            reason = feedback.get("blockReason") or "没有候选结果"
            raise LLMError("CONTENT_FILTERED", f"Gemini 未返回候选：{reason}", request_id=_request_id(response, body))
        candidate = candidates[0] or {}
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        output_text = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))
        finish_reason = str(candidate.get("finishReason") or "")
        request_id = _request_id(response, body)
        self._finish_error(finish_reason, request_id)
        usage = body.get("usageMetadata") or {}
        normalized_usage = {
            "input_tokens": usage.get("promptTokenCount"),
            "output_tokens": usage.get("candidatesTokenCount"),
            "total_tokens": usage.get("totalTokenCount"),
            "cached_tokens": usage.get("cachedContentTokenCount"),
            "thoughts_tokens": usage.get("thoughtsTokenCount"),
        }
        json_data = None
        if wants_json:
            try:
                json_data = _loads_json(output_text)
            except (ValueError, TypeError) as exc:
                raise LLMError("INVALID_RESPONSE", "模型没有返回合法 JSON", request_id=request_id) from exc
        return LLMResponse(
            text=output_text,
            json_data=json_data,
            finish_reason=finish_reason,
            usage=normalized_usage,
            request_id=request_id,
            raw=body,
        )


ADAPTERS: dict[str, type[BaseAdapter]] = {
    "openai_responses": OpenAIResponsesAdapter,
    "openai_chat": OpenAIChatAdapter,
    "anthropic": AnthropicMessagesAdapter,
    "gemini": GeminiGenerateContentAdapter,
}


def get_adapter(provider: Provider, owner_id: str = "") -> BaseAdapter:
    adapter_cls = ADAPTERS.get(provider.protocol)
    if not adapter_cls:
        raise LLMError("INVALID_REQUEST", f"未知协议：{provider.protocol}")
    return adapter_cls(provider, owner_id=owner_id)


def capabilities_for(protocol: str) -> dict[str, Any]:
    common = {
        "json_schema": False,
        "json_mode": True,
        "streaming": True,
        "tools": False,
        "vision": False,
        "top_k": False,
        "penalties": False,
        "seed": False,
        "reasoning": False,
        "cache_usage": False,
    }
    if protocol == "openai_responses":
        return {
            **common,
            "json_schema": True,
            "tools": True,
            "vision": True,
            "reasoning": True,
            "cache_usage": True,
            "notes": ["Responses API 默认有状态；本平台固定 store=false", "部分模型不支持 temperature/top_p"],
        }
    if protocol == "openai_chat":
        return {
            **common,
            "json_schema": True,
            "tools": True,
            "vision": True,
            "penalties": True,
            "seed": True,
            "notes": ["用于只实现 Chat Completions 的兼容端点", "不同端点对 response_format 支持不一致"],
        }
    if protocol == "anthropic":
        return {
            **common,
            "json_schema": True,
            "tools": True,
            "vision": True,
            "top_k": True,
            "cache_usage": True,
            "notes": ["max_tokens 必填；JSON Schema 通过 forced tool use 实现", "system 与 messages 分离"],
        }
    if protocol == "gemini":
        return {
            **common,
            "json_schema": True,
            "tools": True,
            "vision": True,
            "top_k": True,
            "penalties": True,
            "seed": True,
            "notes": ["使用 contents/parts 与 generationConfig", "responseSchema 是 OpenAPI 子集，模型支持度需实测"],
        }
    return common


PROTOCOL_LABELS = {
    "openai_responses": "OpenAI Responses",
    "openai_chat": "OpenAI Chat Completions（兼容）",
    "anthropic": "Anthropic Messages",
    "gemini": "Google Gemini generateContent",
}
