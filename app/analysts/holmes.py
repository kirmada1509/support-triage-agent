"""The data analyst: `holmes ask` in HolmesGPT's container (holmes/Dockerfile) on the shop's
network, with the toolsets in holmes/toolsets.yaml. It can't be imported (its dependencies
conflict with Pydantic AI's), so it runs as a container and answers in a JSON file.

Its --max-steps counts model turns, not tool calls, so the budget is enforced here: stdout says
"Running tool #N <name>" as each call starts, and the container is killed at the time limit or
the first call over budget.
"""

import asyncio
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from app import models_config
from app.analysts import AnalystLimit, AnalystRun
from app.events import ToolCallEvent
from app.history_access import history_url_for_database
from app.models import ToolRecord
from app.settings import ROOT, settings

IMAGE = "sandbox/holmes:0.42.0"
NETWORK = "opentelemetry-demo"
MAX_STEPS = 10  # model turns
OUTPUT_CHARS = 6000  # per tool call kept for the evidence checks

_RUNNING = re.compile(r"^Running tool #(\d+) ([\w.-]+):")


def command(name: str, workdir: Path) -> list[str]:
    """docker run for one question. Keys and the history URL come from the environment."""
    keys = [arg for env in models_config.key_envs("data_analyst") for arg in ("-e", env)]
    model_env = [
        arg
        for k, v in models_config.container_env("data_analyst").items()
        for arg in ("-e", f"{k}={v}")
    ]
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        NETWORK,
        # the history toolset reaches the agent's Postgres on the host (Docker Engine on Linux
        # has no host.docker.internal of its own)
        "--add-host",
        "host.docker.internal:host-gateway",
        "-v",
        f"{ROOT / 'holmes'}:/etc/holmes:ro",
        "-v",
        f"{workdir}:/out",
        *keys,
        *model_env,
        "-e",
        "HISTORY_DB_URL",
        IMAGE,
        "holmes",
        "ask",
        "--config",
        "/etc/holmes/config.yaml",
        "--model",
        models_config.litellm_model("data_analyst"),
        "--max-steps",
        str(MAX_STEPS),
        "--no-interactive",
        "--prompt-file",
        "/out/prompt.md",
        "--json-output-file",
        "/out/result.json",
    ]


def running_call(line: str) -> tuple[int, str] | None:
    """(N, tool) from HolmesGPT's "Running tool #N <tool>: ..." line."""
    if m := _RUNNING.match(line.strip()):
        return int(m.group(1)), m.group(2)
    return None


def records(result: dict) -> list[ToolRecord]:
    """Its JSON output's tool calls, numbered h1, h2... in the order they started."""
    out = []
    for n, c in enumerate(result.get("tool_calls", []), 1):
        res = c.get("result")
        if isinstance(res, dict):
            text = res.get("data") or res.get("error") or ""
            ok = res.get("status") == "success"
        else:
            text, ok = str(res or ""), True
        out.append(
            ToolRecord(
                call_id=f"h{n}",
                provider_call_id=c.get("tool_call_id"),
                tool=c.get("tool_name", "?"),
                args={"command": c.get("description", "")},
                output=str(text)[:OUTPUT_CHARS],
                ok=ok,
            )
        )
    return out


async def _kill(name: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "kill",
        name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


async def ask(
    question: str,
    on_call: Callable[[ToolCallEvent], None],
    *,
    timeout_s: float,
    max_calls: int,
    stage: str = "data_analyst",
) -> AnalystRun:
    workdir = Path(tempfile.mkdtemp(prefix="holmes-"))
    (workdir / "prompt.md").write_text(question)
    name = f"holmes-{uuid.uuid4().hex[:8]}"
    history = history_url_for_database(settings.database_url).replace(
        "localhost", "host.docker.internal"
    )
    t0 = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *command(name, workdir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "HISTORY_DB_URL": history},
    )
    tail: list[str] = []
    try:
        async with asyncio.timeout(timeout_s):
            assert proc.stdout
            async for raw in proc.stdout:
                line = raw.decode(errors="replace")
                tail = (tail + [line])[-40:]
                if started := running_call(line):
                    n, tool = started
                    if n > max_calls:
                        raise AnalystLimit(f"stopped at tool call {n} (budget {max_calls})")
                    on_call(
                        ToolCallEvent(stage=stage, call_id=f"h{n}", tool=tool, status="running")
                    )
            await proc.wait()
    except TimeoutError:
        await _kill(name)
        shutil.rmtree(workdir, ignore_errors=True)
        raise AnalystLimit(f"timed out after {timeout_s:.0f} s") from None
    except AnalystLimit:
        await _kill(name)
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    try:
        if proc.returncode != 0 or not (workdir / "result.json").exists():
            raise RuntimeError(f"holmes exited {proc.returncode}: {''.join(tail)[-1500:]}")
        result = json.loads((workdir / "result.json").read_text())
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return AnalystRun(
        answer=result.get("result") or "",
        calls=records(result),
        cost_usd=result.get("total_cost"),
        seconds=time.monotonic() - t0,
    )
