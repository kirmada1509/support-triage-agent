"""The data analyst's log search: one OpenSearch _search on the shop's otel-logs-* indices.

HolmesGPT's own elasticsearch_search takes the query as free-form objects, which DeepSeek's API
rejects ("An object with no properties is not allowed"); this takes it as a JSON string, so the
tool works on every provider. Usage (HolmesGPT shell-quotes each parameter in toolsets.yaml):

    python3 search_logs.py <index> '<query json>'

Only _search is ever called, on otel-logs-* indices, with at most 50 hits, each condensed to one
line: time, service and version, severity, body, exception and its top frame, trace ID.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

MAX_HITS = 50
DEFAULT_HITS = 20
INDEX = re.compile(r"otel-logs-[0-9*-]*")
MAX_TEXT = 300


def _short(text) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "…"


def search_url(base: str, index: str) -> str:
    if not INDEX.fullmatch(index):
        raise ValueError(f"index must be otel-logs-* or otel-logs-yyyy-MM-dd, got {index!r}")
    return f"{base}/{index}/_search"


def parse_query(text: str) -> dict:
    try:
        body = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError as e:
        raise ValueError(f"query is not JSON: {e}") from None
    if not isinstance(body, dict):
        raise ValueError("query must be a JSON object (an OpenSearch request body)")
    body["size"] = min(int(body.get("size", DEFAULT_HITS)), MAX_HITS)
    return body


def _line(src: dict) -> str:
    res, attrs = src.get("resource", {}), src.get("attributes", {})
    parts = [
        src.get("@timestamp", ""),
        f"{res.get('service.name', '?')} {res.get('service.version', '?')}",
        src.get("severity", {}).get("text", ""),
        _short(src.get("body", "")),
    ]
    if msg := attrs.get("exception.message"):
        parts.append(f"exception: {_short(msg)}")
        frames = [f.strip() for f in attrs.get("exception.stacktrace", "").splitlines()]
        frames = [f for f in frames if f.startswith("at ")]
        if frames:
            parts.append(frames[0])
    if trace := src.get("traceId"):
        parts.append(f"trace {trace}")
    return " | ".join(parts)


def condense(response: dict) -> str:
    if "error" in response:
        return f"OpenSearch error: {json.dumps(response['error'])[:500]}"
    hits = response.get("hits", {})
    total = hits.get("total", {}).get("value", len(hits.get("hits", [])))
    lines = [f"{total} matching log records, showing {len(hits.get('hits', []))}"]
    lines += [_line(h.get("_source", {})) for h in hits.get("hits", [])]
    if aggs := response.get("aggregations"):
        lines.append(f"aggregations: {json.dumps(aggs)[:3000]}")
    return "\n".join(lines)


def main() -> int:
    base = os.environ.get("OPENSEARCH_URL", "http://opensearch:9200")
    try:
        url = search_url(base, sys.argv[1] if len(sys.argv) > 1 else "otel-logs-*")
        body = parse_query(sys.argv[2] if len(sys.argv) > 2 else "")
    except ValueError as e:
        print(e)
        return 1
    request = urllib.request.Request(
        url, json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as r:
            response = json.load(r)
    except urllib.error.HTTPError as e:
        response = json.load(e)
    print(condense(response))
    return 0


if __name__ == "__main__":
    sys.exit(main())
