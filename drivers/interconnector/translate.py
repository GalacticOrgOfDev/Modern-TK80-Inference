"""Translation layer: modern request formats → K80 runtime.

Accepts OpenAI-style chat completions and simple structured requests,
then converts them into a plain prompt for the backend.
"""

from __future__ import annotations

from typing import Any, Dict, List, Union


def messages_to_prompt(messages: List[Dict[str, str]], system_prefix: str = "") -> str:
    """Convert OpenAI-style messages into a single prompt string."""
    parts: List[str] = []
    if system_prefix:
        parts.append(system_prefix.strip())

    for msg in messages:
        role = msg.get("role", "user").lower()
        content = msg.get("content", "").strip()
        if not content:
            continue
        if role == "system":
            parts.append(f"System: {content}")
        elif role == "assistant":
            parts.append(f"Assistant: {content}")
        else:
            parts.append(f"User: {content}")

    parts.append("Assistant:")
    return "\n\n".join(parts)


def translate_request(request: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize a modern request into {prompt, max_tokens, temperature, ...}.

    Accepts:
    - plain string → treated as prompt
    - dict with "prompt"
    - dict with "messages" (OpenAI chat style)
    """
    if isinstance(request, str):
        return {"prompt": request, "max_tokens": 128, "temperature": 0.7}

    if not isinstance(request, dict):
        raise TypeError("request must be str or dict")

    if "messages" in request:
        prompt = messages_to_prompt(request["messages"])
    else:
        prompt = request.get("prompt", "")

    return {
        "prompt": prompt,
        "max_tokens": int(request.get("max_tokens") or request.get("max_new_tokens") or 128),
        "temperature": float(request.get("temperature", 0.7)),
        "stop": request.get("stop"),
    }
