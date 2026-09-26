"""The two Layer 2 analysts as outside calls: HolmesGPT in its container (holmes.py) and
mini-swe-agent driving the read-only codebox (codebox.py). Each returns an AnalystRun or raises
AnalystLimit when it hits its time or call budget; the nodes turn either into Findings.
"""

from pydantic import BaseModel

from app.models import ToolRecord


class AnalystRun(BaseModel):
    answer: str
    calls: list[ToolRecord]
    cost_usd: float | None = None
    seconds: float = 0.0


class AnalystLimit(Exception):
    """The run was stopped at its budget; it answers nothing rather than guess."""
