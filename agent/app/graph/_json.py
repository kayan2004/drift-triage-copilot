"""Tolerant JSON extraction for LLM outputs.

Claude often wraps JSON in markdown fences (```json ... ```) or prepends a
prose preamble. Calling `Model.model_validate_json(raw)` on those outputs
raises ValidationError. This module extracts the JSON object/array from the
raw text before parsing.

Usage:
    from app.graph._json import parse_json_payload
    obj = parse_json_payload(raw, MyModel)
"""
from __future__ import annotations

import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

M = TypeVar("M", bound=BaseModel)

# Matches ```json\n...\n``` or ```\n...\n``` — captures the body.
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_json_text(raw: str) -> str:
    """Return the most-likely JSON substring from `raw`.

    Strategy, in order:
    1. If wrapped in a markdown fence, return the fence body.
    2. Otherwise, slice from the first `{` or `[` to the matching closer.
    3. Fall back to the original string (will trigger ValidationError, which
       is fine — caller will log and use a fallback).
    """
    if not raw:
        return raw

    text = raw.strip()

    # 1. Markdown fence — most common case from Claude
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()

    # 2. Bare JSON with prose prefix/suffix — find first { or [ and matching closer
    start = -1
    opener = ""
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            opener = ch
            break
    if start == -1:
        return text  # no JSON-like content; let caller fail

    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    # Unbalanced — return the slice from start; caller will fail-and-fallback
    return text[start:]


def parse_json_payload(raw: str, model_cls: type[M]) -> M:
    """Parse `raw` into `model_cls`, tolerating fences and prose preambles.

    Raises pydantic.ValidationError if extraction succeeds but the JSON
    doesn't match the schema. Callers should catch that and use a fallback.
    """
    extracted = extract_json_text(raw)
    return model_cls.model_validate_json(extracted)


__all__ = ["extract_json_text", "parse_json_payload", "ValidationError"]
