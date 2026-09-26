"""holmes/search_logs.py, the data analyst's log search: query checks and condensed output,
against a real OpenSearch response (tests/fixtures/opensearch_payment_logs.json)."""

import importlib.util
import json

import pytest

from app.settings import ROOT

spec = importlib.util.spec_from_file_location("search_logs", ROOT / "holmes" / "search_logs.py")
search_logs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(search_logs)

RESPONSE = json.loads((ROOT / "tests" / "fixtures" / "opensearch_payment_logs.json").read_text())


@pytest.mark.parametrize("index", ["otel-logs-*", "otel-logs-2026-09-26", "otel-logs-2026-09-2*"])
def test_log_indices_are_accepted(index):
    assert search_logs.search_url("http://opensearch:9200", index) == (
        f"http://opensearch:9200/{index}/_search"
    )


@pytest.mark.parametrize(
    "index",
    ["_all", "*", ".opendistro-security", "otel-logs-*/_delete_by_query?x=", "otel-logs-*,x"],
)
def test_only_log_indices_are_searched(index):
    with pytest.raises(ValueError, match="otel-logs-"):
        search_logs.search_url("http://opensearch:9200", index)


def test_the_query_is_json_with_a_capped_size():
    assert search_logs.parse_query('{"query": {"match_all": {}}}') == {
        "query": {"match_all": {}},
        "size": 20,
    }
    assert search_logs.parse_query('{"size": 500}')["size"] == 50
    assert search_logs.parse_query("") == {"size": 20}


@pytest.mark.parametrize(("text", "error"), [("{query:", "not JSON"), ("[1]", "JSON object")])
def test_a_bad_query_says_what_is_wrong(text, error):
    with pytest.raises(ValueError, match=error):
        search_logs.parse_query(text)


def test_hits_are_condensed_to_one_line_each():
    lines = search_logs.condense(RESPONSE).splitlines()
    assert lines[0] == "88 matching log records, showing 3"
    first = lines[1]
    for part in (
        "2026-09-26T05:36:31.887Z",
        "payment v1.4.0",
        "warn",
        "Charge declined.",
        "The credit card (ending 5100) expired on 9/2026.",
        "at module.exports.charge (/usr/src/app/charge.js:89:13)",
        "trace 9c2d114269fa725bbdba3110f598c1f5",
    ):
        assert part in first, part
    assert "Transaction complete." in lines[3] and "exception" not in lines[3]


def test_aggregations_are_kept():
    response = RESPONSE | {
        "aggregations": {"by_version": {"buckets": [{"key": "v1.4.0", "doc_count": 88}]}}
    }
    assert '"v1.4.0"' in search_logs.condense(response).splitlines()[-1]


def test_an_opensearch_error_is_passed_on():
    assert "index_not_found" in search_logs.condense(
        {"error": {"type": "index_not_found_exception", "reason": "no such index [otel-logs-x]"}}
    )


def test_long_multiline_messages_stay_on_one_short_line():
    src = {
        "body": "Exporting failed.",
        "attributes": {"exception.message": "not retryable\n" * 100},
    }
    line = search_logs.condense({"hits": {"hits": [{"_source": src}]}}).splitlines()[1]
    assert "\n" not in line and len(line) < 400 and line.endswith("…")
