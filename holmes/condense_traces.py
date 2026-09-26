#!/usr/bin/env python3
"""Condense Jaeger API JSON (stdin) so the model never sees raw trace JSON.

Default: one line per trace: ID, start (UTC), duration, the request (root span), user.id, and the
root cause: the deepest error on the request's path, with its service's version and the services
it passed through. --tree: one trace as an indented span tree (service@version/operation), errors
marked, repeats and the rest folded into counts, background streams that outlive the request
hidden.
Standard library only; tests/test_condense_traces.py pins the output on real responses.
"""

from __future__ import annotations  # runs on whatever python3 HolmesGPT has

import json
import sys
from datetime import datetime, timezone

KEEP_TAGS = ("user.id", "rpc.grpc.status_code")  # plus every demo.* attribute
MAX_TREE_LINES = 80
MAX_MESSAGE = 300


class Trace:
    def __init__(self, trace: dict):
        self.id = trace["traceID"]
        self.processes = trace["processes"]
        self.spans = {s["spanID"]: s for s in trace["spans"]}
        self.parent: dict[str, str | None] = {}
        self.children: dict[str | None, list[dict]] = {}
        for s in self.spans.values():
            parent = next(
                (
                    r["spanID"]
                    for r in s.get("references", [])
                    if r["refType"] == "CHILD_OF" and r["spanID"] in self.spans
                ),
                None,
            )
            self.parent[s["spanID"]] = parent
            self.children.setdefault(parent, []).append(s)
        for kids in self.children.values():
            kids.sort(key=lambda s: s["startTime"])
        self.root = self._request_root()

    def service(self, span: dict) -> str:
        return self.processes[span["processID"]]["serviceName"]

    def version(self, span: dict) -> str:
        tags = self.processes[span["processID"]].get("tags", [])
        return next((str(t["value"]) for t in tags if t["key"] == "service.version"), "-")

    def subtree(self, span: dict) -> list[dict]:
        out, stack = [], [span]
        while stack:
            s = stack.pop()
            out.append(s)
            stack.extend(self.children.get(s["spanID"], []))
        return out

    def in_request(self, span: dict) -> bool:
        """False for background spans (e.g. a flag provider's stream) that outlive the request."""
        root_end = self.root["startTime"] + self.root["duration"]
        return span["startTime"] + span["duration"] <= root_end + max(self.root["duration"], 1e6)

    def _request_root(self) -> dict:
        """The root whose subtree holds an error, else the longest root. Roots are spans without a
        parent in the trace; start times aren't used, since services' clocks differ slightly."""
        roots = self.children.get(None, [])
        failing = [r for r in roots if any(is_error(s) for s in self.subtree(r))]
        return max(failing or roots, key=lambda s: s["duration"])

    def depth(self, span: dict) -> int:
        d, sid = 0, span["spanID"]
        while self.parent.get(sid):
            d, sid = d + 1, self.parent[sid]
        return d

    def path(self, span: dict) -> list[str]:
        services, sid = [], span["spanID"]
        while sid:
            name = self.service(self.spans[sid])
            if not services or services[-1] != name:
                services.append(name)
            sid = self.parent.get(sid)
        return services[::-1]

    def root_cause(self) -> dict | None:
        errors = [s for s in self.subtree(self.root) if is_error(s) and self.in_request(s)]
        if not errors:
            return None
        return max(errors, key=lambda s: (self.depth(s), bool(message(s)), -s["startTime"]))


def tags(span: dict) -> dict:
    return {t["key"]: t["value"] for t in span.get("tags", [])}


def is_error(span: dict) -> bool:
    t = tags(span)
    return t.get("error") in (True, "true") or t.get("otel.status_code") == "ERROR"


def message(span: dict) -> str:
    t = tags(span)
    msg = t.get("exception.message") or t.get("error.message") or t.get("otel.status_description")
    if not msg:
        fields = (f for log in span.get("logs", []) for f in log.get("fields", []))
        msg = next((f["value"] for f in fields if f["key"] == "exception.message"), "")
    msg = " ".join(str(msg).split())
    return msg if len(msg) <= MAX_MESSAGE else msg[:MAX_MESSAGE] + "…"


def attributes(span: dict) -> str:
    t = tags(span)
    keep = [k for k in KEEP_TAGS if k in t] + sorted(k for k in t if k.startswith("demo."))
    return " ".join(f"{k}={_value(t[k])}" for k in keep)


def _value(v) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def summary(trace: Trace) -> str:
    root = trace.root
    user = next((tags(s)["user.id"] for s in trace.spans.values() if "user.id" in tags(s)), "-")
    start = datetime.fromtimestamp(root["startTime"] / 1e6, timezone.utc).strftime("%H:%M:%S")  # noqa: UP017
    cause = trace.root_cause()
    error = "-"
    if cause:
        error = (
            f"{trace.service(cause)} {trace.version(cause)} {cause['operationName']}: "
            f"{message(cause) or 'no message'} (via {' > '.join(trace.path(cause))})"
        )
    return (
        f"{trace.id} {start} {root['duration'] / 1000:.0f}ms "
        f"{trace.service(root)}/{root['operationName']} user={user} error={error}"
    )


def render_tree(trace: Trace) -> str:
    """Errors, spans with demo.* attributes, and the path from each up to the root. Other spans
    under a parent fold into one line of counts; a repeated call without errors shows once."""
    spans = [s for s in trace.subtree(trace.root) if trace.in_request(s)]
    hidden = sum(1 for s in trace.spans.values() if not trace.in_request(s))
    marked = [s for s in spans if is_error(s) or any(k.startswith("demo.") for k in tags(s))]
    keep: set[str] = set()
    for s in marked:
        sid = s["spanID"]
        while sid and sid not in keep:
            keep.add(sid)
            sid = trace.parent.get(sid)
    lines = [f"trace {trace.id}"]

    def label(s: dict) -> str:
        return f"{trace.service(s)}@{trace.version(s)}/{s['operationName']}"

    def walk(span: dict, depth: int) -> None:
        err = f" ERROR {message(span)}" if is_error(span) else ""
        extra = attributes(span)
        lines.append(
            f"{'  ' * depth}{label(span)} {span['duration'] / 1000:.1f}ms{err}"
            + (f" {extra}" if extra else "")
        )
        folded: dict[str, int] = {}
        shown: set[str] = set()
        repeats: dict[str, int] = {}
        for child in trace.children.get(span["spanID"], []):
            fails = any(is_error(s) for s in trace.subtree(child) if trace.in_request(s))
            if child["spanID"] in keep and label(child) in shown and not fails:
                repeats[label(child)] = repeats.get(label(child), 0) + 1
            elif child["spanID"] in keep:
                shown.add(label(child))
                walk(child, depth + 1)
            elif trace.in_request(child):
                n = len([s for s in trace.subtree(child) if trace.in_request(s)])
                folded[label(child)] = folded.get(label(child), 0) + n
        for name, n in repeats.items():
            lines.append(f"{'  ' * (depth + 1)}(+{n} more {name}, no errors)")
        if folded:
            top = sorted(folded.items(), key=lambda kv: -kv[1])
            text = ", ".join(f"{name} x{n}" for name, n in top[:4])
            more = f" and {len(top) - 4} more" if len(top) > 4 else ""
            lines.append(f"{'  ' * (depth + 1)}(+{sum(folded.values())} spans: {text}{more})")

    walk(trace.root, 1)
    if hidden:
        lines.append(f"({hidden} background spans that outlive the request hidden)")
    if len(lines) > MAX_TREE_LINES:
        lines = lines[: MAX_TREE_LINES - 1] + [f"(… {len(lines) - MAX_TREE_LINES + 1} more lines)"]
    return "\n".join(lines)


def condense(response: dict, tree: bool = False) -> str:
    data = response.get("data") or []
    if not data:
        return "no traces found"
    if tree:
        return render_tree(Trace(data[0]))
    return "\n".join([f"{len(data)} traces"] + [summary(Trace(t)) for t in data])


def main() -> None:
    print(condense(json.load(sys.stdin), tree="--tree" in sys.argv))


if __name__ == "__main__":
    main()
