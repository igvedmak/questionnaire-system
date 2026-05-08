"""AI-powered analysis of questionnaire responses.

Streams a structured analysis report to stdout given a template and its
submitted questionnaires. Uses adaptive thinking for deeper insights.
"""

from __future__ import annotations

import json
from typing import Iterator

from ..config import settings
from ..domain.types import Questionnaire, Template

_SYSTEM = """You are a data analyst specializing in survey research. Analyze questionnaire
response data and produce a concise, insightful report. Structure your report with:

1. **Overview** — response count, submission rate, date range
2. **Key Findings** — most significant patterns and trends (bullet points)
3. **Question-by-Question Breakdown** — for each question: distribution, notable outliers
4. **Segments & Cross-cuts** — any interesting correlations between answers
5. **Recommendations** — 2-3 actionable insights based on the data

Be specific and data-driven. Mention actual values, percentages, and counts where possible."""


def _client():
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(
            "The 'llm' extra is required: pip install questionnaire[llm]"
        ) from exc

    api_key = settings.llm_api_key
    if not api_key:
        raise RuntimeError(
            "QST_LLM_API_KEY is not set. Add it to .env or the environment."
        )
    return anthropic.Anthropic(api_key=api_key)


def _build_summary(template: Template, questionnaires: list[Questionnaire]) -> str:
    submitted = [q for q in questionnaires if q.is_submitted]
    drafts = [q for q in questionnaires if not q.is_submitted]

    lines: list[str] = [
        f"Template: {template.title} (id={template.id})",
        f"Total responses: {len(questionnaires)} ({len(submitted)} submitted, {len(drafts)} drafts)",
        "",
        "Questions:",
    ]
    for q in template.questions:
        lines.append(f"  [{q.type}] {q.id}: {q.prompt}")

    lines += ["", "Response data (submitted only):"]
    for i, qn in enumerate(submitted[:200], 1):  # cap at 200 to stay within context
        answers = {
            qid: av.model_dump()
            for qid, av in qn.answers.items()
        }
        lines.append(f"  Response {i} (id={qn.id}): {json.dumps(answers)}")

    if len(submitted) > 200:
        lines.append(f"  ... and {len(submitted) - 200} more responses (truncated)")

    return "\n".join(lines)


def stream_analysis(
    template: Template,
    questionnaires: list[Questionnaire],
) -> Iterator[str]:
    """Yield text chunks of an AI analysis report.

    Usage::

        for chunk in stream_analysis(template, questionnaires):
            print(chunk, end="", flush=True)
    """
    client = _client()
    summary = _build_summary(template, questionnaires)

    with client.messages.stream(
        model=settings.llm_model,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": f"Please analyze the following questionnaire response data:\n\n{summary}",
            }
        ],
    ) as stream:
        for text in stream.text_stream:
            yield text
