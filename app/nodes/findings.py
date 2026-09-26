"""Turn an analyst's text answer + tool log into Findings, and check the evidence.

HolmesGPT and mini-swe-agent answer in text. A Pydantic AI call (role "findings") converts the
answer and its tool log into Findings; code then drops any evidence that doesn't point at a tool
call that actually happened. Only what an analyst queried or read during the run counts.
"""

from app.models import Findings


async def to_findings(agent: str, answer: str, tool_log: list[dict]) -> Findings:
    raise NotImplementedError("phase 6: Pydantic AI Agent(output_type=Findings)")


def check_evidence(findings: Findings, call_ids: set[str]) -> Findings:
    """Keep evidence tied to a real tool call; cap confidence when nothing is left."""
    kept = [e for e in findings.evidence if e.call_id in call_ids]
    confidence = findings.confidence if kept else min(findings.confidence, 0.3)
    return findings.model_copy(update={"evidence": kept, "confidence": confidence})
