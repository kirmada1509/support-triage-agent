"""The code index of the real fork at both tags (make sandbox): what the helper commands will
answer for the demo tickets. Run with `make test-sandbox`; no database or model is needed.
"""

import os
from pathlib import Path

import pytest

from app.indexer import build, export
from app.nodes._config import ownership
from app.settings import ROOT
from tests.test_codebox_helpers import BIN

pytestmark = pytest.mark.sandbox

SANDBOX = Path(os.environ.get("SANDBOX_DIR", ROOT.parent / "opentelemetry-demo")).resolve()
TAGS = ("v1.3.0", "v1.4.0")


@pytest.fixture(scope="module")
def indexes() -> dict[str, dict[str, build.CodeIndex]]:
    if not (SANDBOX / ".git").exists():
        pytest.fail(f"no fork at {SANDBOX}; run make sandbox (or set SANDBOX_DIR)")
    return {
        tag: {
            s: build.index_at(SANDBOX, s, o["path"].rstrip("/"), tag)
            for s, o in ownership().items()
        }
        for tag in TAGS
    }


def errors(index: build.CodeIndex) -> dict[str, int]:
    return {e.text: e.line for e in index.errors}


@pytest.mark.parametrize("tag", TAGS)
def test_every_service_is_indexed(indexes, tag):
    for service, index in indexes[tag].items():
        assert index.symbols and index.errors, f"{service}@{tag}"
        assert all(s.file.startswith(ownership()[service]["path"]) for s in index.symbols)


@pytest.mark.parametrize("tag", TAGS)
def test_grpc_handlers(indexes, tag):
    rpcs = {r.method: f"{r.file}:{r.line}" for i in indexes[tag].values() for r in i.rpcs}
    assert rpcs["PaymentService/Charge"] == "src/payment/index.js:12"
    assert rpcs["CartService/EmptyCart"].startswith("src/cart/src/services/CartService.cs:")
    assert rpcs["CheckoutService/PlaceOrder"].startswith("src/checkout/main.go:")
    assert {m for m in rpcs if m.startswith("ProductCatalogService/")} == {
        "ProductCatalogService/GetProduct",
        "ProductCatalogService/ListProducts",
        "ProductCatalogService/SearchProducts",
    }
    assert not indexes[tag]["quote"].rpcs  # quote is HTTP


def test_the_expiry_message_moves_with_the_v1_4_0_change(indexes):
    expired = "The credit card (ending ${lastFourDigits}) expired on ${month}/${year}."
    assert errors(indexes["v1.3.0"]["payment"])[expired] == 87
    assert errors(indexes["v1.4.0"]["payment"])[expired] == 89


def test_the_amex_message_is_in_both_versions(indexes):
    amex = "Sorry, we cannot process ${cardType} credit cards. Only VISA or MasterCard is accepted."
    assert all(amex in errors(indexes[tag]["payment"]) for tag in TAGS)


def test_flag_reads(indexes):
    flags = {(f.flag, i.service) for i in indexes["v1.4.0"].values() for f in i.flags}
    assert {("paymentFailure", "payment"), ("cartFailure", "cart")} <= flags


def test_the_change_summary_names_the_refactor():
    summary = build.change_summary(SANDBOX, "src/payment", "v1.3.0", "v1.4.0")
    assert "refactor: simplify card expiry comparison" in summary
    assert "charge.js" in summary


def test_the_helpers_find_a_customer_quote_in_the_real_index(indexes, tmp_path):
    import subprocess

    export.write(tmp_path, list(indexes["v1.4.0"].values()), {})
    env = {**os.environ, "PATH": f"{BIN}:{os.environ['PATH']}", "INDEX_DIR": str(tmp_path)}
    out = subprocess.run(
        ["lookup-error", "The credit card (ending 4242) expired on 9/2026."],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out.strip().splitlines() == [
        "src/payment/charge.js:89 payment: "
        "The credit card (ending ${lastFourDigits}) expired on ${month}/${year}."
    ]
