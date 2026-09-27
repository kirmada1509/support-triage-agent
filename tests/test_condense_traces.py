"""holmes/condense_traces.py on real Jaeger responses (tests/fixtures/jaeger_*.json): what the
data analyst sees instead of raw trace JSON."""

import importlib.util
import json

import yaml

from app.settings import ROOT

FIXTURES = ROOT / "tests" / "fixtures"
spec = importlib.util.spec_from_file_location("condense", ROOT / "holmes" / "condense_traces.py")
condense = importlib.util.module_from_spec(spec)
spec.loader.exec_module(condense)


def load(name: str) -> dict:
    data = json.loads((FIXTURES / name).read_text())
    return data if "data" in data else {"data": [data]}


SEARCH = load("jaeger_search_expired_cards.json")
QUOTE = load("jaeger_quote_11_items.json")


def test_a_search_is_one_line_per_trace():
    lines = condense.condense(SEARCH).splitlines()
    assert lines[0] == "3 traces"
    assert len(lines) == 4


def test_the_summary_names_the_request_the_user_and_the_root_cause():
    """The root is the request (not whichever service's clock ran early), and the error is the
    deepest one on the request's path, with that service's version: payment v1.4.0's decline,
    not the frontend's wrapper around it or the flagd streams that outlive the request."""
    line = condense.condense(SEARCH).splitlines()[2]
    assert line.startswith("cf9aa1232b9d598155aa24c6ebab62e3 06:01:35 ")
    assert "frontend-proxy/POST" in line
    assert "user=figma-shopper-03" in line
    assert (
        "error=payment v1.4.0 charge: The credit card (ending 4242) expired on 9/2026." in line
    ), line
    assert "via frontend-proxy > frontend > checkout > payment" in line
    assert "DEADLINE_EXCEEDED" not in line and "quote/" not in line and "quote@" not in line


def test_every_trace_in_the_search_finds_its_own_decline():
    lines = condense.condense(SEARCH).splitlines()[1:]
    for user, card in (("11", "4444"), ("03", "4242"), ("12", "5100")):
        line = next(x for x in lines if f"user=figma-shopper-{user}" in x)
        assert f"payment v1.4.0 charge: The credit card (ending {card})" in line


def test_a_trace_without_errors_says_so():
    line = condense.condense(QUOTE).splitlines()[1]
    assert line.startswith("e640818de4eb3da43a4075fa807f2936 ")
    assert "load-generator/user_checkout_multi" in line and line.endswith("error=-")
    assert "quote@v1.4.0 items=11 total=197.78" in line


def test_the_tree_keeps_the_attributes_that_matter():
    tree = condense.condense(QUOTE, tree=True)
    line = next(x for x in tree.splitlines() if "calculate-quote" in x)
    assert "quote@" in line
    assert "demo.shipping.quote.cost.total=197.78" in line
    assert "demo.shipping.quote.items_count=11" in line


def test_the_tree_folds_repeats_and_fits_without_cutting():
    """A whole load-generator session (168 spans) fits under the cap: repeated calls without
    errors show once, spans without demo.* attributes are counted."""
    lines = condense.condense(QUOTE, tree=True).splitlines()
    assert len(lines) < condense.MAX_TREE_LINES and not any("more lines" in x for x in lines)
    assert "(+3 more load-generator@3.1.0/user_add_to_cart, no errors)" in [
        x.strip() for x in lines
    ]
    assert any("spans: cart@3.1.0/valkey-cart:6379" in x for x in lines)


def test_the_tree_marks_the_error_path_and_hides_background_streams():
    tree = condense.condense({"data": [SEARCH["data"][1]]}, tree=True)
    charge = next(x for x in tree.splitlines() if "payment@v1.4.0/charge" in x)
    assert "ERROR" in charge and "demo.payment.card_type=visa" in charge
    assert "expired on 9/2026" in charge
    assert "EventStream" not in tree and "background" in tree


def test_no_traces():
    assert condense.condense({"data": []}) == "no traces found"
    assert condense.condense({"data": None}) == "no traces found"


def test_jaeger_can_find_successful_service_traces_without_an_error_filter():
    toolsets = yaml.safe_load((ROOT / "holmes" / "toolsets.yaml").read_text())["toolsets"]
    tool = next(t for t in toolsets["jaeger"]["tools"] if t["name"] == "find_traces")
    command = tool["command"]
    assert "curl -s -G" in command and "service={{ service }}" in command
    assert "operation={{ operation }}" in command
    assert "start={{ start_us }}" in command and "end={{ end_us }}" in command
    assert "tags=" not in command and "/tools/condense_traces.py" in command
