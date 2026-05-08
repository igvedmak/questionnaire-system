"""AI-powered questionnaire template generation.

Sends a natural-language description to any LLM via litellm and returns
a validated Template object. Provider is selected via QST_LLM_MODEL.

Supported examples:
  anthropic/claude-opus-4-7   (Anthropic — default)
  gpt-4o                      (OpenAI)
  gemini/gemini-1.5-pro       (Google)
  ollama/llama3               (local Ollama — no key needed)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ..config import settings
from ..domain.types import Template
from ..domain.validation import validate_template

_SYSTEM = """You are a questionnaire designer. Generate a complete questionnaire template as JSON.

RULES:
- Output ONLY valid JSON — no markdown fences, no explanation, no preamble
- Question IDs must be unique across the ENTIRE template, using snake_case
- Single-select questions MUST have MORE THAN 2 options (at least 3)
- Multi-select questions must have at least 2 options
- Use diverse question types to make the questionnaire rich
- Follow-ups make questionnaires smarter — use them when contextually appropriate

SCHEMA (follow exactly):
{
  "id": "tpl_<snake_case>",
  "title": "<human-readable title>",
  "description": "<one-sentence description>",
  "questions": [<question objects>],
  "created_at": "<ISO-8601 timestamp>"
}

QUESTION OBJECTS (use the exact "type" literal shown):
  boolean:      {"type": "boolean", "id": "...", "prompt": "...?", "follow_ups": []}
  single_select:{"type": "single_select", "id": "...", "prompt": "...", "options": ["A","B","C"], "follow_ups": []}
  multi_select: {"type": "multi_select", "id": "...", "prompt": "...", "options": ["A","B","C"], "follow_ups": []}
  date:         {"type": "date", "id": "...", "prompt": "..."}
  free_text:    {"type": "free_text", "id": "...", "prompt": "...", "pii": false}
  number:       {"type": "number", "id": "...", "prompt": "...", "min": null, "max": null, "integer": false}
  rating:       {"type": "rating", "id": "...", "prompt": "...", "min_val": 1, "max_val": 5}
  email:        {"type": "email", "id": "...", "prompt": "..."}

FOLLOW-UP OBJECTS (nest inside a question's follow_ups list):
  boolean follow-up:    {"when_equals": true, "questions": [<question objects>]}
  select follow-up:     {"when_option_selected": "<option value>", "questions": [<question objects>]}"""


def _completion_kwargs() -> dict:
    try:
        import litellm  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "The 'llm' extra is required: pip install questionnaire[llm]"
        ) from exc

    if not settings.llm_api_key and not settings.llm_base_url:
        raise RuntimeError(
            "LLM API key not configured. Set QST_LLM_API_KEY in .env or the environment."
        )

    model = settings.llm_model
    kwargs: dict = {"model": model, "max_tokens": 4096}
    if settings.llm_api_key:
        kwargs["api_key"] = settings.llm_api_key
    if settings.llm_base_url:
        kwargs["base_url"] = settings.llm_base_url

    # Claude-specific: enable adaptive thinking for better structured output
    if "claude" in model or model.startswith("anthropic/"):
        kwargs["thinking"] = {"type": "adaptive"}

    return kwargs


def generate_template(description: str, *, max_retries: int = 2) -> Template:
    """Generate a validated Template from a natural-language description.

    Raises RuntimeError if the llm extra is missing, the API key is unset,
    or if the model produces JSON that fails validation after retries.
    """
    import litellm

    kwargs = _completion_kwargs()
    now = datetime.now(timezone.utc).isoformat()

    prompt = (
        f"Generate a comprehensive questionnaire template for:\n\n{description}\n\n"
        f'Use this timestamp for created_at: "{now}"'
    )

    last_err: Exception | None = None
    for _ in range(max_retries):
        response = litellm.completion(
            **kwargs,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )

        text = response.choices[0].message.content or ""

        # Strip markdown fences if the model added them despite instructions
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("```", 2)[1]
            if stripped.startswith("json"):
                stripped = stripped[4:]
            stripped = stripped.rstrip("`").strip()

        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as exc:
            last_err = exc
            prompt = (
                f"The JSON you returned was invalid ({exc}). "
                f"Please regenerate the template for:\n\n{description}\n\n"
                f'created_at: "{now}". Output ONLY valid JSON.'
            )
            continue

        try:
            tpl = Template.model_validate(raw)
        except Exception as exc:
            last_err = exc
            prompt = (
                f"The JSON did not match the schema ({exc}). "
                f"Please regenerate the template for:\n\n{description}\n\n"
                f'created_at: "{now}". Output ONLY valid JSON.'
            )
            continue

        result = validate_template(tpl)
        if not result.ok:
            last_err = ValueError("; ".join(result.errors))
            prompt = (
                f"The template failed validation: {'; '.join(result.errors)}. "
                f"Please fix and regenerate for:\n\n{description}\n\n"
                f'created_at: "{now}". Output ONLY valid JSON.'
            )
            continue

        return tpl

    raise RuntimeError(
        f"Failed to generate a valid template after {max_retries} attempts: {last_err}"
    )
