"""OpenAI-compatible LLM client — Kimi K3 primary, DeepSeek fallback."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Tests set this to bypass network calls.
_MOCK_HANDLER: Any | None = None


def set_mock_handler(handler: Any | None) -> None:
    """Replace the real API with a callable(messages, tools) -> assistant message dict."""
    global _MOCK_HANDLER
    _MOCK_HANDLER = handler


def _provider_config(name: str) -> dict[str, str] | None:
    if name == "kimi":
        key = os.getenv("KIMI_API_KEY")
        if not key:
            return None
        return {
            "api_key": key,
            "base_url": os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1").rstrip("/"),
            "model": os.getenv("KIMI_MODEL", "kimi-k3"),
        }
    if name == "deepseek":
        key = os.getenv("DEEPSEEK_API_KEY")
        if not key:
            return None
        return {
            "api_key": key,
            "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        }
    return None


def _provider_chain() -> list[dict[str, str]]:
    primary = os.getenv("LLM_PROVIDER", "kimi").lower()
    order = [primary] + [p for p in ("kimi", "deepseek") if p != primary]
    configs: list[dict[str, str]] = []
    for name in order:
        cfg = _provider_config(name)
        if cfg:
            configs.append(cfg)
    return configs


def chat_completion(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    timeout_s: float = 90.0,
) -> dict[str, Any]:
    """One chat/completions round-trip; returns the assistant message dict."""
    if _MOCK_HANDLER is not None:
        return _MOCK_HANDLER(messages, tools)

    payload: dict[str, Any] = {
        "messages": messages,
        "temperature": 0.2,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    last_error: Exception | None = None
    for cfg in _provider_chain():
        payload["model"] = cfg["model"]
        url = f"{cfg['base_url']}/chat/completions"
        headers = {
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=timeout_s) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            choice = data["choices"][0]
            return choice["message"]
        except Exception as exc:  # noqa: BLE001 — try next provider
            logger.warning("LLM provider %s failed: %s", cfg["model"], exc)
            last_error = exc
    if last_error:
        raise RuntimeError(f"All LLM providers failed: {last_error}") from last_error
    raise RuntimeError("No LLM provider configured (set KIMI_API_KEY or DEEPSEEK_API_KEY)")


def message_content_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return ""
