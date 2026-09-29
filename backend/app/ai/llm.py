"""LLM client wrapper — Phase-0 stub.

Phase 2 wires this to a real frontier LLM API (see project-plan §4.6: bake-off
between Claude Sonnet / GPT-5 class models; DeepSeek or Qwen as fallback).
Engineering discipline (§7.0): the LLM may only speak from tool-returned data,
regulation citations must carry clause numbers, and structured output must
pass schema validation with automatic retry.
"""

import os


def get_llm_client() -> None:
    """Return a configured LLM client.

    TODO(phase-2): read provider + model from env (LLM_PROVIDER, LLM_MODEL,
    LLM_API_KEY) and return a real client. Returns None in Phase 0 so the app
    boots with no credentials.
    """
    if not os.getenv("LLM_API_KEY"):
        return None
    raise NotImplementedError("LLM client lands in Phase 2 (step 2.2)")


def complete(messages: list[dict], tools: list[dict] | None = None) -> str:
    """Single entry point for chat completion with tool calling.

    TODO(phase-2): implement the question -> tool call -> grounded answer loop.
    """
    raise NotImplementedError("LLM completion lands in Phase 2 (step 2.2)")
