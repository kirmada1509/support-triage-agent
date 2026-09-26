"""A service card: one model call per service and commit reads the service's code and writes a
short orientation (purpose, entry points, business rules, dependencies, error messages). It points
the codebase analyst at the right place; it is never evidence. Error messages the code doesn't
contain are dropped.
"""

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from app import models_config
from app.indexer.build import CodeIndex

MAX_SOURCE_CHARS = 150_000

INSTRUCTIONS = """You write a service card for engineers and a code-reading agent: what one service
of an online shop does, as its code shows at this commit. Be concrete and short. Business rules are
the checks and calculations the code applies, stated as the code states them (limits, comparisons,
which inputs are refused), each with its file:line. Copy error messages exactly from the list you
are given and say what triggers each. Only describe what the code shows; don't guess intent."""


class ErrorMeaning(BaseModel):
    message: str = Field(description="exactly as in the list of error messages")
    meaning: str = Field(description="what triggers it, with file:line")


class ServiceCard(BaseModel):
    purpose: str
    entry_points: list[str] = Field(description="RPC or HTTP handlers, each with file:line")
    business_rules: list[str]
    dependencies: list[str] = Field(description="other services, databases, flags it calls")
    error_messages: list[ErrorMeaning]


def prompt(index: CodeIndex, description: str) -> str:
    parts = [f"Service: {index.service}\nWhat it's for (from the team): {description}\n"]
    if index.rpcs:
        rpcs = "\n".join(f"{r.method} -> {r.file}:{r.line}" for r in index.rpcs)
        parts.append(f"gRPC handlers:\n{rpcs}\n")
    errors = "\n".join(f"{e.file}:{e.line}: {e.text}" for e in index.errors)
    parts.append(f"Error messages in the code:\n{errors or '(none)'}\n")
    budget = MAX_SOURCE_CHARS
    for path, text in sorted(index.files.items()):
        numbered = "\n".join(f"{n}: {line}" for n, line in enumerate(text.splitlines(), 1))
        if len(numbered) > budget:
            parts.append(f"=== {path} (left out: over the size budget)")
            continue
        budget -= len(numbered)
        parts.append(f"=== {path}\n{numbered}")
    return "\n".join(parts)


async def _run(text: str) -> ServiceCard:
    agent = Agent(
        models_config.pydantic_ai_model("indexer"),
        output_type=ServiceCard,
        instructions=INSTRUCTIONS,
    )
    result = await agent.run(text, usage_limits=models_config.LIMITS["indexer"])
    return result.output


def render(index: CodeIndex, c: ServiceCard) -> str:
    known = {e.text for e in index.errors}
    errors = [e for e in c.error_messages if e.message in known]

    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {i}" for i in items) or "- (none)"

    return (
        f"# {index.service} at {index.git_sha[:8]}\n\n{c.purpose}\n\n"
        f"## Entry points\n{bullets(c.entry_points)}\n\n"
        f"## Business rules\n{bullets(c.business_rules)}\n\n"
        f"## Dependencies\n{bullets(c.dependencies)}\n\n"
        f"## Error messages\n{bullets([f'`{e.message}`: {e.meaning}' for e in errors])}\n"
    )


async def write_card(index: CodeIndex, description: str) -> str:
    return render(index, await _run(prompt(index, description)))
