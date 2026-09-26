"""scenarios/: the scenario logic against a simulated shop, the ticket text it sends, parsing
Jaeger's traces, signing tickets, and recording flags. Nothing here needs the shop or Postgres."""

import hashlib
import hmac
import inspect
import json
import re
import secrets
import sys
from argparse import Namespace
from datetime import datetime

import pytest
import yaml

from app.api.main import sign
from app.settings import ROOT

sys.path.insert(0, str(ROOT / "scenarios"))
import record  # noqa: E402
import scenario  # noqa: E402
import send_ticket  # noqa: E402
from scenario import COMET_BOOK, THIS_MONTH, Order, Shopper, Span  # noqa: E402

VERSIONED = ("payment", "quote", "checkout", "product-catalog")
PRODUCTS = [
    "0PUK6V6EV0",
    "1YMWWN1N4O",
    "2ZYFJ3GM2N",
    "66VCHSJNUP",
    "6E92ZMYYFZ",
    "9SIQT8TOJO",
    "HQTGWGPNH4",
    "L9ECAV7KIM",
    "LS4PSXUNUM",
    "OLJCESPC7Z",
]


class FakeShop:
    """The shop as the scenarios see it, each versioned service on v1.3.0 or v1.4.0. v1.4.0 has
    the planted bugs, unless fixed=True, when it behaves like v1.3.0. The paymentFailure flag at
    25% fails every fourth charge (also nothing, when fixed)."""

    url = "http://shop.test"

    def __init__(self, fixed: bool = False):
        self.fixed = fixed
        self.versions = dict.fromkeys(VERSIONED, "v1.3.0")
        self.flag = "off"
        self.orders: list[Order] = []
        self.traces: dict[str, list[Span]] = {}
        self.charges = 0

    def buggy(self, service: str) -> bool:
        return self.versions[service] == "v1.4.0" and not self.fixed

    def reachable(self) -> bool:
        return True

    def charge_error(self, s: Shopper) -> str | None:
        self.charges += 1
        if self.flag == "25%" and not self.fixed and self.charges % 4 == 0:
            return "Payment request failed. Invalid token. demo.user_context.loyalty_level=gold"
        c = s.card
        if c.kind not in ("visa", "mastercard"):
            return (
                f"Sorry, we cannot process {c.kind} credit cards. "
                "Only VISA or MasterCard is accepted."
            )
        now, expiry = THIS_MONTH[1] * 12 + THIS_MONTH[0], c.year * 12 + c.month
        if now > expiry or (self.buggy("payment") and now == expiry):
            return f"The credit card (ending {c.number[-4:]}) expired on {c.month}/{c.year}."
        return None

    def order(self, s: Shopper, items, phase: str, check_cart=False) -> Order:
        trace_id = secrets.token_hex(16)
        qty = sum(q for _, q in items)
        per_item = 17.98 if self.buggy("quote") and qty > 10 else 8.99
        v = self.versions
        spans = [
            Span("checkout", v["checkout"], "oteldemo.CheckoutService/PlaceOrder", None, {}),
            Span(
                "quote",
                v["quote"],
                "calculate-quote",
                None,
                {
                    "demo.shipping.quote.cost.total": round(per_item * qty, 2),
                    "demo.shipping.quote.items_count": qty,
                },
            ),
        ]
        error = self.charge_error(s)
        if error:
            spans.append(Span("payment", v["payment"], "charge", error, {}))
        emptied = not error and not (self.buggy("checkout") and s.currency != "USD")
        if emptied:
            spans.append(
                Span("checkout", v["checkout"], "oteldemo.CartService/EmptyCart", None, {})
            )
        self.traces[trace_id] = spans
        o = Order(s, phase, items, datetime.now().astimezone(), 422 if error else 200, trace_id)
        if not error and s.currency == "USD":
            o.shipping_usd = round(per_item * qty, 2)
        if check_cart:
            o.cart_after = 0 if emptied else qty
        self.orders.append(o)
        return o

    def spans(self, trace_id, until=bool, wait=60):
        return self.traces.get(trace_id)

    def products(self) -> list[dict]:
        hidden = {COMET_BOOK} if self.buggy("product-catalog") else set()
        return [{"id": p} for p in PRODUCTS if p not in hidden]

    def product_page(self, product_id: str) -> int:
        return 200

    def trace_url(self, trace_id: str) -> str:
        return f"{self.url}/jaeger/ui/trace/{trace_id}"


@pytest.fixture
def shop(monkeypatch):
    """A buggy FakeShop wired in place of the real shop, deploys and flags; no waiting."""
    return use(monkeypatch, FakeShop())


@pytest.fixture
def fixed_shop(monkeypatch):
    return use(monkeypatch, FakeShop(fixed=True))


def use(monkeypatch, shop: FakeShop) -> FakeShop:
    monkeypatch.setattr(scenario, "Shop", lambda url: shop)
    monkeypatch.setattr(scenario, "deployed", lambda service: shop.versions[service])
    monkeypatch.setattr(scenario, "deploy", lambda s, v, record=True: shop.versions.update({s: v}))
    monkeypatch.setattr(scenario, "flag_variant", lambda name: shop.flag)
    monkeypatch.setattr(scenario, "set_flag", lambda n, v, record=True: setattr(shop, "flag", v))
    monkeypatch.setattr(scenario, "require_agent_db", lambda: None)
    monkeypatch.setattr(scenario.time, "sleep", lambda s: None)
    return shop


def run(name: str, shop: FakeShop) -> scenario.Checks:
    check = scenario.Checks(shop)
    scenario.SCENARIOS[name](shop, check, Namespace(gap=0, rounds=2, spacing=0))
    return check


# --- scenario logic -----------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["3", "4", "5", "6", "cart", "catalog"])
def test_scenario_reproduces_its_bug(name, shop):
    assert run(name, shop).passed


@pytest.mark.parametrize("name", ["4", "5", "6", "cart", "catalog"])
def test_scenario_fails_without_its_bug(name, fixed_shop):
    """A scenario must never report a bug that isn't there."""
    assert not run(name, fixed_shop).passed


def test_bug_scenarios_deploy_v1_4_0_after_a_v1_3_0_baseline(shop):
    run("4", shop)
    phases = [o.phase for o in shop.orders]
    assert phases[0] == "v1.3.0" and phases[-1] == "v1.4.0"
    assert shop.versions["payment"] == "v1.4.0"


def test_scenarios_use_their_own_tenant_shoppers():
    """Each scenario's shoppers are figma-shopper-01..20 and no two scenarios share one, so
    their orders never mix in one shopper's history."""
    seen: dict[int, str] = {}
    for name, fn in scenario.SCENARIOS.items():
        for n in map(int, re.findall(r"shopper\((\d+)", inspect.getsource(fn) if fn else "")):
            assert 1 <= n <= 20
            assert seen.setdefault(n, name) == name, f"shopper {n} in {seen[n]} and {name}"


# --- the ticket each scenario sends -------------------------------------------------------------


def main(monkeypatch, capsys, *args: str) -> str:
    monkeypatch.setattr(sys, "argv", ["scenario.py", *args])
    scenario.main()
    return capsys.readouterr().out


def test_ticket_4_gets_the_first_failure_time(shop, monkeypatch, capsys):
    out = main(monkeypatch, capsys, "4", "--no-send", "--gap", "0")
    first = min(o.at for o in shop.orders if not o.ok and o.shopper.n in (3, 11))
    assert f"failed around {first:%H:%M}" in out and "10:15" not in out
    assert "scenario 4 reproduced" in out


def test_ticket_6_gets_the_flag_time_in_subject_and_body(shop, monkeypatch, capsys):
    out = main(monkeypatch, capsys, "6", "--no-send", "--gap", "0")
    assert "11:05" not in out
    assert re.search(r"subject: About 1 in 4 checkouts have failed since \d\d:\d\d", out)
    assert re.search(r"Since about \d\d:\d\d today", out)


def test_ticket_is_not_sent_when_the_bug_does_not_reproduce(fixed_shop, monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(scenario, "send", lambda *a: sent.append(a))
    monkeypatch.setattr(scenario, "require_api", lambda: None)
    with pytest.raises(SystemExit, match="did not reproduce; no ticket sent"):
        main(monkeypatch, capsys, "5", "--gap", "0")
    assert sent == []


def test_every_demo_ticket_has_a_scenario():
    tickets = yaml.safe_load((ROOT / "scenarios" / "tickets.yaml").read_text())["tickets"]
    assert [t["id"] for t in tickets] == [str(n) for n in range(1, 8)]
    assert all(t["id"] in scenario.SCENARIOS for t in tickets)


def test_part_of_day():
    at = lambda h: datetime(2026, 9, 26, h)  # noqa: E731
    parts = [scenario.part_of_day(at(h)) for h in (8, 13, 19)]
    assert parts == ["this morning", "this afternoon", "this evening"]


# --- cards and checkout payloads ----------------------------------------------------------------


def luhn(number: str) -> bool:
    digits = [int(d) for d in reversed(number)]
    return sum(d if i % 2 == 0 else sum(divmod(d * 2, 10)) for i, d in enumerate(digits)) % 10 == 0


def test_test_cards_pass_validation_and_have_the_right_network():
    cards = scenario.VISA + scenario.MASTERCARD + [scenario.AMEX]
    assert all(luhn(n) for n in cards)
    kinds = {n: scenario.Card(n, 1, 2030).kind for n in cards}
    assert kinds[scenario.AMEX] == "amex" and scenario.AMEX.endswith("0005")  # ticket 3's card
    assert {kinds[n] for n in scenario.VISA} == {"visa"}
    assert {kinds[n] for n in scenario.MASTERCARD} == {"mastercard"}


def test_checkout_body_matches_the_load_generator_people_json():
    body = scenario.shopper(3, scenario.AMEX, currency="EUR").checkout_body()
    assert set(body) == {"userId", "userCurrency", "email", "address", "creditCard"}
    assert set(body["address"]) == {"streetAddress", "zipCode", "city", "state", "country"}
    assert body["creditCard"] == {
        "creditCardNumber": "3782-822463-10005",
        "creditCardExpirationMonth": scenario.LATER[0],
        "creditCardExpirationYear": scenario.LATER[1],
        "creditCardCvv": 123,
    }
    assert body["userId"] == "figma-shopper-03" and body["userCurrency"] == "EUR"
    assert scenario.Card(scenario.VISA[0], 1, 2030).formatted == "4242-4242-4242-4242"


# --- Jaeger -------------------------------------------------------------------------------------


def test_spans_from_a_real_expired_card_trace():
    """tests/fixtures/jaeger_expired_card.json: a real payment v1.4.0 decline from Jaeger, kept to
    checkout's and payment's spans."""
    trace = json.loads((ROOT / "tests" / "fixtures" / "jaeger_expired_card.json").read_text())
    spans = scenario._spans(trace)
    charge = next(s for s in spans if s.service == "payment" and s.operation == "charge")
    assert charge.version == "v1.4.0"
    assert re.fullmatch(r"The credit card \(ending 4242\) expired on \d+/\d{4}\.", charge.error)
    assert any(s.operation == "oteldemo.CheckoutService/PlaceOrder" and s.error for s in spans)
    assert not any(s.operation.endswith("EmptyCart") for s in spans)  # failed before emptying


# --- sending and recording ----------------------------------------------------------------------


def test_sent_ticket_is_signed_the_way_the_webhook_checks(monkeypatch):
    posted = {}

    class Ok:
        def raise_for_status(self):
            pass

    def post(url, content, headers):
        posted.update(url=url, content=content, headers=headers)
        return Ok()

    monkeypatch.setattr(send_ticket.httpx, "post", post)
    ticket_id = send_ticket.send("subject", "body")
    assert posted["url"].endswith("/webhooks/pylon")
    assert posted["headers"]["x-pylon-signature"] == sign(posted["content"])
    payload = json.loads(posted["content"])
    assert payload["id"] == ticket_id and payload["tenant_id"] == "figma-merch"
    forged = hmac.new(b"wrong", posted["content"], hashlib.sha256).hexdigest()
    assert posted["headers"]["x-pylon-signature"] != forged


def test_flag_change_without_recording(tmp_path, monkeypatch):
    f = tmp_path / "demo.flagd.json"
    flags = {
        "paymentFailure": {"defaultVariant": "off", "variants": {"off": 0, "25%": 0.25}},
        "adFailure": {"defaultVariant": "off", "variants": {"off": False, "on": True}},
    }
    f.write_text(json.dumps({"flags": flags}, indent=2) + "\n")
    monkeypatch.setenv("FLAG_RECORD", "0")
    monkeypatch.setattr(record, "run", lambda coro: pytest.fail("recorded"))
    record.flag(str(f), "paymentFailure", "25%")
    changed = json.loads(f.read_text())["flags"]
    assert changed["paymentFailure"]["defaultVariant"] == "25%"
    assert changed["adFailure"] == flags["adFailure"]
    with pytest.raises(SystemExit, match="no variant '30%'"):
        record.flag(str(f), "paymentFailure", "30%")
