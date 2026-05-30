"""Shared LLM helpers for the agentic search package.

Kept separate from research.py so the search package is self-contained: the
evaluator, discovery, and targeted modules all call Claude through here. Two
models are used to keep cost bounded — a cheap Haiku classifier for Pass 1 and
Sonnet for the heavier Pass 2 evaluation and query formulation.

Environment:
    ANTHROPIC_API_KEY  — required for any LLM call.
    IRRBB_PASS1_MODEL  — override the Pass 1 (classifier) model.
    IRRBB_PASS2_MODEL  — override the Pass 2 (evaluator) model.
"""

from __future__ import annotations

import json
import os
import re

# Defaults. Pass 1 is the cheap title+summary classifier; Pass 2 is the full
# content + wiki-context evaluation and the discovery/targeted query writer.
PASS1_MODEL = os.environ.get("IRRBB_PASS1_MODEL", "claude-haiku-4-5")
PASS2_MODEL = os.environ.get("IRRBB_PASS2_MODEL", "claude-sonnet-4-6")


def get_client():
    """Return an Anthropic client. Lazy-imported so the package imports without
    the SDK installed (e.g. for `cli.py queue`, which makes no LLM calls)."""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set — required for agentic search LLM calls. "
            "Export it, or run only the no-LLM commands (queue/review/approve/reject)."
        )
    return anthropic.Anthropic(api_key=api_key)


def call_text(prompt: str, model: str, max_tokens: int = 1024) -> str:
    """Single-turn text completion. Returns the first text block, stripped."""
    client = get_client()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def extract_json(text: str):
    """Parse a JSON object from an LLM response, tolerating markdown fences and
    surrounding prose. Raises ValueError if no JSON object can be parsed."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fall back to the first {...} span in the text.
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"Could not parse JSON from LLM response: {text[:300]!r}")
