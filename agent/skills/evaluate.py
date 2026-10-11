"""Skill: LLM-judge that evaluates the quality of a generated test file."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import anthropic

logger = logging.getLogger(__name__)

_JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "claude-haiku-4-5-20251001")

_VERDICT_TOOL: dict = {
    "name": "report_verdict",
    "description": "Report the quality verdict for the generated test file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "approved": {
                "type": "boolean",
                "description": "True if the tests meet quality standards.",
            },
            "score": {
                "type": "integer",
                "description": "Quality score from 1 (poor) to 5 (excellent).",
            },
            "issues": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Specific, actionable quality problems found. "
                    "Empty list when approved=true."
                ),
            },
        },
        "required": ["approved", "score", "issues"],
    },
}

_SYSTEM = """\
You are a strict test quality reviewer. You receive a source-code diff and the generated \
test file for that diff.

Approve (approved=true, score 4-5) only when ALL of these hold:
1. The tests cover the key behaviours that changed in the diff — not just the happy path.
2. Assertions are specific: they check actual values or side-effects, \
not merely that a result is not None.
3. At least one error path or invalid-input case is tested when the source handles such cases.
4. The tests would detect a regression if the relevant code path were changed or removed.

Reject (approved=false) and list specific, actionable issues when any condition is violated.

Scoring guide:
5 — all changed paths covered, assertions are precise
4 — good coverage with only minor gaps
3 — basic coverage, some important paths missing
2 — only the happy path tested, or assertions are too weak to catch regressions
1 — trivial assertions or effectively no meaningful coverage
"""


@dataclass
class QualityVerdict:
    approved: bool
    score: int
    issues: list[str] = field(default_factory=list)


def evaluate_test_quality(
    source_diff: str,
    test_content: str,
    kind: str = "unknown",
) -> QualityVerdict:
    """Call an LLM judge to assess whether generated tests are high quality.

    Uses a cheap, fast model (Haiku) for the single-turn structured evaluation.
    Fails open on any API error so a judge outage never blocks the main workflow.
    """
    client = anthropic.Anthropic()
    prompt = (
        f"## Source diff ({kind})\n\n```diff\n{source_diff[:4000]}\n```\n\n"
        f"## Generated test file\n\n```\n{test_content[:6000]}\n```"
    )
    try:
        response = client.messages.create(
            model=_JUDGE_MODEL,
            max_tokens=512,
            system=_SYSTEM,
            tools=[_VERDICT_TOOL],
            tool_choice={"type": "tool", "name": "report_verdict"},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as exc:
        logger.warning("Judge API call failed (%s) — failing open.", exc)
        return QualityVerdict(approved=True, score=0, issues=["Judge unavailable."])

    for block in response.content:
        if block.type == "tool_use" and block.name == "report_verdict":
            data = block.input
            return QualityVerdict(
                approved=bool(data["approved"]),
                score=int(data["score"]),
                issues=list(data.get("issues", [])),
            )

    logger.warning("Judge returned no verdict block — failing open.")
    return QualityVerdict(approved=True, score=0, issues=["Judge returned no verdict."])
