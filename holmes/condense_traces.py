#!/usr/bin/env python3
"""Condense Jaeger API JSON (stdin) so the model never sees raw trace JSON.

Default: one line per trace (ID, start, duration, root operation, user.id, service.version, first
error). --tree: one trace as an indented span tree, errors marked. Standard library only.
"""

from __future__ import annotations  # runs on whatever python3 HolmesGPT has

import json
import sys
from datetime import datetime, timezone

KEEP_TAGS = (
    "user.id",
    "app.user.id",
    "service.version",
    "error.message",
    "exception.message",
    "rpc.grpc.status_code",
    "app.payment.card_type",
)


def tags(span: dict) -> dict:
    return {t["key"]: t["value"] for t in span.get("tags", [])}


def first_error(spans: list[dict]) -> str | None:
    """The earliest error span that carries a message (usually the root cause, not the caller)."""
    found = []
    for s in sorted(spans, key=lambda s: s["startTime"]):
        t = tags(s)
        if t.get("error") in (True, "true") or t.get("otel.status_code") == "ERROR":
            msg = (
                t.get("exception.message")
                or t.get("error.message")
                or t.get("otel.status_description", "")
            )
            for log in s.get("logs", []):
                for f in log.get("fields", []):
                    if f["key"] in ("exception.message", "message") and not msg:
                        msg = f["value"]
            found.append((s["operationName"], msg))
    if not found:
        return None
    op, msg = next(((o, m) for o, m in found if m), found[0])
    return f"{op}: {msg}"[:300]


def service_of(trace: dict, span: dict) -> str:
    return trace["processes"][span["processID"]]["serviceName"]


def summary(trace: dict) -> str:
    spans = trace["spans"]
    root = min(spans, key=lambda s: s["startTime"])
    user = next(
        (
            tags(s).get("user.id") or tags(s).get("app.user.id")
            for s in spans
            if tags(s).get("user.id") or tags(s).get("app.user.id")
        ),
        "-",
    )
    version = next(
        (
            t["value"]
            for p in trace["processes"].values()
            for t in p.get("tags", [])
            if t["key"] == "service.version"
        ),
        "-",
    )
    utc = timezone.utc  # noqa: UP017 (older Pythons have no datetime.UTC)
    start = datetime.fromtimestamp(root["startTime"] / 1e6, utc).strftime("%H:%M:%S")
    return (
        f"{trace['traceID']} {start} {root['duration'] / 1000:.0f}ms "
        f"{service_of(trace, root)}/{root['operationName']} user={user} version={version} "
        f"error={first_error(spans) or '-'}"
    )


def tree(trace: dict) -> str:
    spans = {s["spanID"]: s for s in trace["spans"]}
    children: dict[str | None, list[dict]] = {}
    for s in spans.values():
        parent = next(
            (
                r["spanID"]
                for r in s.get("references", [])
                if r["refType"] == "CHILD_OF" and r["spanID"] in spans
            ),
            None,
        )
        children.setdefault(parent, []).append(s)
    lines: list[str] = [f"trace {trace['traceID']}"]

    def walk(parent: str | None, depth: int) -> None:
        for s in sorted(children.get(parent, []), key=lambda s: s["startTime"]):
            t = tags(s)
            err = " ERROR" if t.get("error") in (True, "true") else ""
            extra = " ".join(f"{k}={t[k]}" for k in KEEP_TAGS if k in t)
            lines.append(
                f"{'  ' * depth}{service_of(trace, s)}/{s['operationName']} "
                f"{s['duration'] / 1000:.1f}ms{err} {extra}".rstrip()
            )
            walk(s["spanID"], depth + 1)

    walk(None, 1)
    return "\n".join(lines[:80])


def main() -> None:
    data = json.load(sys.stdin).get("data", [])
    if not data:
        print("no traces found")
        return
    if "--tree" in sys.argv:
        print(tree(data[0]))
    else:
        print(f"{len(data)} traces")
        for t in data:
            print(summary(t))


if __name__ == "__main__":
    main()
