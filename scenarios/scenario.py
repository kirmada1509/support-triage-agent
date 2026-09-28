"""Set up a demo ticket's condition in the sandbox shop, place matching orders, send the ticket.

uv run python scenarios/scenario.py 4              # same as: make scenario-4
uv run python scenarios/scenario.py 4 --no-send    # place the orders, print the ticket instead
uv run python scenarios/scenario.py 8              # tickets 8 and 9: the cart and catalog bugs
uv run python scenarios/scenario.py cart --no-send # the same, by name

Orders go through the shop's frontend API the way its load generator places them
(src/load-generator/locustfile.py): POST /api/cart, then POST /api/checkout with a
people.json-shaped body plus userId. Bug scenarios place baseline orders on v1.3.0, deploy
v1.4.0 (recorded, like a real deploy), place the same orders again, check in Jaeger that the bug
reproduced, then send the ticket with the real times filled in. A scenario that doesn't reproduce
exits 1 and sends nothing.

Every scenario has its own Figma Merch shoppers (figma-shopper-NN), and every order its own
W3C trace ID, so the summary links straight to each order's trace.
"""

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from send_ticket import send, template

AGENT_DIR = Path(__file__).resolve().parent.parent
SANDBOX_DIR = Path(os.environ.get("SANDBOX_DIR", AGENT_DIR.parent / "opentelemetry-demo"))
SHOP_URL = os.environ.get("SHOP_URL", "http://localhost:8080")

# Products from the shop's catalog (src/postgresql/init.sql).
LENS_KIT, FLASHLIGHT, SOLAR_FILTER, COMET_BOOK = (
    "L9ECAV7KIM",
    "LS4PSXUNUM",
    "6E92ZMYYFZ",
    "HQTGWGPNH4",
)

ADDRESSES = {
    "USD": {
        "streetAddress": "760 Market Street",
        "zipCode": "94102",
        "city": "San Francisco",
        "state": "CA",
        "country": "United States",
    },
    "EUR": {
        "streetAddress": "Friedrichstrasse 68",
        "zipCode": "10117",
        "city": "Berlin",
        "state": "BE",
        "country": "Germany",
    },
    "CAD": {
        "streetAddress": "100 Queen Street West",
        "zipCode": "M5H 2N2",
        "city": "Toronto",
        "state": "ON",
        "country": "Canada",
    },
}


# --- shoppers and cards -------------------------------------------------------------------------


@dataclass(frozen=True)
class Card:
    number: str  # digits only
    month: int
    year: int

    @property
    def kind(self) -> str:
        return {"3": "amex", "4": "visa", "5": "mastercard"}[self.number[0]]

    @property
    def formatted(self) -> str:
        """Grouped with dashes, as in the load generator's people.json."""
        n = self.number
        if self.kind == "amex":
            return f"{n[:4]}-{n[4:10]}-{n[10:]}"
        return "-".join(n[i : i + 4] for i in range(0, 16, 4))

    def __str__(self) -> str:
        return f"{self.kind} ending {self.number[-4:]}, exp {self.month}/{self.year}"


# Card networks' published test numbers.
VISA = ["4242424242424242", "4012888888881881", "4111111111111111", "4000056655665556"]
MASTERCARD = ["5555555555554444", "5105105105105100"]
AMEX = "378282246310005"  # ends 0005, as ticket 3 says

_now = datetime.now(UTC)  # the payment service checks expiry against its own (UTC) clock
THIS_MONTH = (_now.month, _now.year)
LATER = (_now.month, _now.year + 2)


@dataclass(frozen=True)
class Shopper:
    n: int
    card: Card
    currency: str = "USD"

    @property
    def id(self) -> str:
        return f"figma-shopper-{self.n:02d}"

    def checkout_body(self) -> dict:
        return {
            "userId": self.id,
            "userCurrency": self.currency,
            "email": f"{self.id}@shoppers.example",
            "address": ADDRESSES[self.currency],
            "creditCard": {
                "creditCardNumber": self.card.formatted,
                "creditCardExpirationMonth": self.card.month,
                "creditCardExpirationYear": self.card.year,
                "creditCardCvv": 123,
            },
        }


def shopper(n: int, number: str, expiry: tuple[int, int] = LATER, currency: str = "USD") -> Shopper:
    return Shopper(n, Card(number, *expiry), currency)


# --- the shop -----------------------------------------------------------------------------------


@dataclass
class Order:
    shopper: Shopper
    phase: str
    items: list[tuple[str, int]]
    at: datetime
    status: int
    trace_id: str
    shipping_usd: float | None = None  # only for USD orders
    cart_after: int | None = None  # items left in the cart after checkout

    @property
    def ok(self) -> bool:
        return self.status == 200

    @property
    def quantity(self) -> int:
        return sum(q for _, q in self.items)


@dataclass
class Span:
    service: str
    version: str
    operation: str
    error: str | None
    attrs: dict


class Shop:
    def __init__(self, url: str):
        self.url = url
        self.http = httpx.Client(base_url=url, timeout=30)
        self.orders: list[Order] = []

    def reachable(self) -> bool:
        try:
            return self.http.get("/api/products", params={"currencyCode": "USD"}).status_code == 200
        except httpx.HTTPError:
            return False

    def order(
        self, s: Shopper, items: list[tuple[str, int]], phase: str, check_cart=False
    ) -> Order:
        """Add the items to an empty cart and check out, all in one trace. Emptying the cart first
        gets a trace of its own, so an order's trace has no EmptyCart but checkout's."""
        self.http.request("DELETE", "/api/cart", json={"userId": s.id})
        trace_id = secrets.token_hex(16)
        h = {"traceparent": f"00-{trace_id}-{secrets.token_hex(8)}-01"}
        for product, qty in items:
            item = {"productId": product, "quantity": qty}
            self.http.post("/api/cart", json={"item": item, "userId": s.id}, headers=h)
        at = datetime.now().astimezone()
        r = self.http.post(
            "/api/checkout", params={"currencyCode": s.currency}, json=s.checkout_body(), headers=h
        )
        o = Order(s, phase, items, at, r.status_code, trace_id)
        if o.ok and s.currency == "USD":
            cost = r.json()["shippingCost"]
            o.shipping_usd = int(cost.get("units", 0)) + cost.get("nanos", 0) / 1e9
        if check_cart:
            cart = self.http.get(
                "/api/cart", params={"sessionId": s.id, "currencyCode": s.currency}
            )
            o.cart_after = sum(i["quantity"] for i in cart.json().get("items", []))
        self.orders.append(o)
        self._print(o)
        return o

    def _print(self, o: Order) -> None:
        result = "ok" if o.ok else f"FAILED ({o.status})"
        extra = f"  shipping ${o.shipping_usd:.2f}" if o.shipping_usd is not None else ""
        extra += f"  cart after: {o.cart_after} items" if o.cart_after is not None else ""
        print(
            f"  {o.at:%H:%M:%S}  {o.phase:<8} {o.shopper.id}  {o.shopper.card!s:<34} "
            f"{o.shopper.currency} x{o.quantity:<3} {result}{extra}"
        )

    def products(self) -> list[dict]:
        r = self.http.get("/api/products", params={"currencyCode": "USD"})
        r.raise_for_status()
        return r.json()

    def product_page(self, product_id: str) -> int:
        return self.http.get(
            f"/api/products/{product_id}", params={"currencyCode": "USD"}
        ).status_code

    def spans(
        self, trace_id: str, until: Callable[[list[Span]], bool] = bool, wait: float = 60
    ) -> list[Span] | None:
        """The trace's spans from Jaeger once `until` holds. Each service exports in its own
        batches, so a trace arrives in pieces; at the deadline, whatever has arrived (None if
        nothing has)."""
        deadline = time.monotonic() + wait
        spans = None
        while True:
            r = self.http.get(f"/jaeger/ui/api/traces/{trace_id}")
            data = r.json().get("data") if r.status_code == 200 else None
            if data:
                spans = _spans(data[0])
                if until(spans):
                    return spans
            if time.monotonic() > deadline:
                return spans
            time.sleep(3)

    def trace_url(self, trace_id: str) -> str:
        return f"{self.url}/jaeger/ui/trace/{trace_id}"


def _spans(trace: dict) -> list[Span]:
    procs = {
        pid: (p["serviceName"], {t["key"]: t["value"] for t in p.get("tags", [])})
        for pid, p in trace["processes"].items()
    }
    out = []
    for s in sorted(trace["spans"], key=lambda s: s["startTime"]):
        service, ptags = procs[s["processID"]]
        tags = {t["key"]: t["value"] for t in s.get("tags", [])}
        error = None
        if tags.get("error") in (True, "true") or tags.get("otel.status_code") == "ERROR":
            error = tags.get("otel.status_description") or next(
                (
                    f["value"]
                    for log in s.get("logs", [])
                    for f in log["fields"]
                    if f["key"] == "exception.message"
                ),
                "error",
            )
        out.append(
            Span(service, str(ptags.get("service.version", "")), s["operationName"], error, tags)
        )
    return out


# --- sandbox controls ---------------------------------------------------------------------------


def deployed(service: str) -> str:
    var = service.upper().replace("-", "_") + "_VERSION="
    f = SANDBOX_DIR / "versions.env"
    lines = f.read_text().splitlines() if f.exists() else []
    return next((line.removeprefix(var) for line in lines if line.startswith(var)), "v1.3.0")


def deploy(service: str, version: str, record: bool = True) -> None:
    env = {**os.environ, "SANDBOX_DIR": str(SANDBOX_DIR), "DEPLOY_RECORD": "1" if record else "0"}
    subprocess.run([AGENT_DIR / "scenarios" / "deploy.sh", service, version], check=True, env=env)


def ensure(service: str, version: str) -> None:
    """Put a service on a version without recording a deploy (scenario setup, not the story)."""
    if deployed(service) != version:
        print(f"resetting {service} to {version} (not recorded)")
        deploy(service, version, record=False)


def flag_variant(name: str) -> str:
    data = json.loads((SANDBOX_DIR / "src" / "flagd" / "demo.flagd.json").read_text())
    return data["flags"][name]["defaultVariant"]


def set_flag(name: str, variant: str, record: bool = True) -> None:
    env = {**os.environ, "SANDBOX_DIR": str(SANDBOX_DIR), "FLAG_RECORD": "1" if record else "0"}
    subprocess.run([AGENT_DIR / "scenarios" / "flag.sh", name, variant], check=True, env=env)


def pause(seconds: float, why: str) -> None:
    if seconds > 0:
        print(f"waiting {seconds:.0f}s {why}")
        time.sleep(seconds)


def part_of_day(t: datetime) -> str:
    return "this morning" if t.hour < 12 else "this afternoon" if t.hour < 17 else "this evening"


# --- checks -------------------------------------------------------------------------------------


class Checks:
    def __init__(self, shop: Shop):
        self.shop = shop
        self.results: list[bool] = []

    def __call__(self, ok: bool, what: str) -> bool:
        print(f"  {'PASS' if ok else 'FAIL'}  {what}")
        self.results.append(ok)
        return ok

    def errors(self, orders: list[Order], service: str) -> list[Span | None]:
        """Each order's first error span from `service` in Jaeger (None: no error span)."""

        def first_error(spans: list[Span]) -> Span | None:
            return next((s for s in spans if s.service == service and s.error), None)

        out = []
        for o in orders:
            spans = self.shop.spans(o.trace_id, until=first_error)
            if not self(spans is not None, f"{o.shopper.id} {o.at:%H:%M:%S} trace in Jaeger"):
                out.append(None)
                continue
            out.append(first_error(spans))
        return out

    @property
    def passed(self) -> bool:
        return all(self.results)


# --- scenarios ----------------------------------------------------------------------------------
# Each returns the ticket's text replacements ({phrase in tickets.yaml: real value}), or None for
# a scenario without a ticket.

Scenario = Callable[[Shop, Checks, argparse.Namespace], dict[str, str] | None]


def amex(shop: Shop, check: Checks, a: argparse.Namespace) -> dict[str, str]:
    """Ticket 3: a shopper's Amex card is declined. Intended behaviour, on any payment version."""
    amex_shopper, control = shopper(7, AMEX), shopper(8, VISA[0])
    tries = []
    for _ in range(3):  # "They tried three times"
        tries.append(shop.order(amex_shopper, [(SOLAR_FILTER, 1)], "amex"))
        time.sleep(a.spacing)
    ok = shop.order(control, [(SOLAR_FILTER, 1)], "control")

    print("checking Jaeger")
    check(all(not o.ok for o in tries), "all three Amex checkouts failed")
    check(ok.ok, "a Visa checkout at the same time went through")
    errors = check.errors(tries, "payment")
    check(
        all(e and "cannot process amex" in e.error for e in errors),
        "payment's error is the card-type rule: " + (errors[0].error if errors[0] else "none"),
    )
    return {"this morning": part_of_day(tries[0].at)}


def expiry(shop: Shop, check: Checks, a: argparse.Namespace) -> dict[str, str]:
    """Ticket 4: payment v1.4.0 rejects cards in their expiry month."""
    this_month = [
        shopper(3, VISA[0], THIS_MONTH),  # "figma-shopper-03 and figma-shopper-11 both failed"
        shopper(11, MASTERCARD[0], THIS_MONTH),
        shopper(4, VISA[1], THIS_MONTH),
        shopper(12, MASTERCARD[1], THIS_MONTH),
    ]
    later = [shopper(5, VISA[2]), shopper(13, VISA[3])]
    ensure("payment", "v1.3.0")
    base = [shop.order(s, [(LENS_KIT, 1)], "v1.3.0") for s in this_month + later]
    pause(a.gap, "so the deploy stands apart in the metrics")
    deploy("payment", "v1.4.0")
    after = []
    for _ in range(a.rounds):
        after += [shop.order(s, [(LENS_KIT, 1)], "v1.4.0") for s in this_month + later]
        time.sleep(a.spacing)

    failing = [o for o in after if o.shopper in this_month]
    print("checking Jaeger")
    check(all(o.ok for o in base), "on v1.3.0 every card went through, this month's included")
    check(all(not o.ok for o in failing), "on v1.4.0 every card expiring this month failed")
    check(all(o.ok for o in after if o.shopper in later), "on v1.4.0 later expiries went through")
    errors = check.errors(failing, "payment")
    month, year = THIS_MONTH
    check(
        all(
            e and f"expired on {month}/{year}" in e.error and e.version == "v1.4.0" for e in errors
        ),
        f"payment v1.4.0 says expired on {month}/{year}: "
        + (errors[0].error if errors[0] else "none"),
    )
    first = min(o.at for o in failing if o.shopper.n in (3, 11))
    return {"around 10:15": f"around {first:%H:%M}", "this morning": part_of_day(first)}


def bulk_quote(shop: Shop, check: Checks, a: argparse.Namespace) -> dict[str, str]:
    """Ticket 5: quote v1.4.0 charges shipping twice on orders above 10 items."""
    orders = [
        (shopper(15, VISA[2]), [(LENS_KIT, 20)]),
        (shopper(16, VISA[3]), [(FLASHLIGHT, 12), (SOLAR_FILTER, 12)]),
        (shopper(17, MASTERCARD[0]), [(LENS_KIT, 2)]),  # a small order, for comparison
    ]
    ensure("quote", "v1.3.0")
    base = [shop.order(s, items, "v1.3.0") for s, items in orders]
    pause(a.gap, "so the deploy stands apart in the metrics")
    deploy("quote", "v1.4.0")
    after = []
    for _ in range(a.rounds):
        after += [shop.order(s, items, "v1.4.0") for s, items in orders]
        time.sleep(a.spacing)

    def per_item(os_: list[Order], bulk: bool) -> set[float]:
        return {
            round(o.shipping_usd / o.quantity, 2)
            for o in os_
            if o.ok and o.shipping_usd is not None and (o.quantity > 10) == bulk
        }

    check(all(o.ok for o in base + after), "every order went through")
    check(per_item(base, True) | per_item(base, False) == {8.99}, "v1.3.0: $8.99 per item")
    check(per_item(after, True) == {17.98}, f"v1.4.0 bulk: {per_item(after, True)} per item")
    check(per_item(after, False) == {8.99}, f"v1.4.0 small: {per_item(after, False)} per item")
    print("checking Jaeger")

    def quote_span(spans: list[Span]) -> Span | None:
        return next((s for s in spans if s.operation == "calculate-quote"), None)

    quote = quote_span(shop.spans(after[0].trace_id, until=quote_span) or [])
    check(
        quote is not None and quote.version == "v1.4.0",
        "quote v1.4.0's calculate-quote span: "
        + (json.dumps({k: v for k, v in quote.attrs.items() if "quote" in k}) if quote else "none"),
    )
    return {}


def payment_flag(shop: Shop, check: Checks, a: argparse.Namespace) -> dict[str, str]:
    """Ticket 6: the paymentFailure flag fails about a quarter of charges. Leaves the flag on."""
    shoppers = [shopper(18, VISA[0]), shopper(19, MASTERCARD[1]), shopper(20, VISA[1])]
    if flag_variant("paymentFailure") != "off":
        print("turning paymentFailure off first (not recorded)")
        set_flag("paymentFailure", "off", record=False)
        time.sleep(5)
    base = [shop.order(shoppers[i % 3], [(FLASHLIGHT, 1)], "flag off") for i in range(6)]
    pause(a.gap, "so the flag change stands apart in the metrics")
    set_flag("paymentFailure", "25%")
    flag_at = datetime.now().astimezone()
    time.sleep(10)  # flagd sees the file change, then streams it to payment
    after = []
    for i in range(24):
        after.append(shop.order(shoppers[i % 3], [(FLASHLIGHT, 1)], "flag 25%"))
        time.sleep(a.spacing / 3)

    failed = [o for o in after if not o.ok]
    print("checking Jaeger")
    check(all(o.ok for o in base), "with the flag off every order went through")
    check(
        0 < len(failed) < len(after), f"with the flag at 25%, {len(failed)} of {len(after)} failed"
    )
    errors = check.errors(failed, "payment")
    check(
        all(e and "Invalid token" in e.error for e in errors),
        "payment's error is the flag's: " + (errors[0].error if errors and errors[0] else "none"),
    )
    print("paymentFailure is still at 25%; after the demo: make flag f=paymentFailure v=off")
    return {"11:05": f"{flag_at:%H:%M}"}


def cart(shop: Shop, check: Checks, a: argparse.Namespace) -> dict[str, str]:
    """Ticket 8: checkout v1.4.0 leaves non-USD orders' items in the cart."""
    shoppers = [
        shopper(1, VISA[0], currency="EUR"),
        shopper(2, VISA[1], currency="CAD"),
        shopper(9, VISA[2]),
    ]
    ensure("checkout", "v1.3.0")
    base = [shop.order(s, [(LENS_KIT, 2)], "v1.3.0", check_cart=True) for s in shoppers]
    pause(a.gap, "so the deploy stands apart in the metrics")
    deploy("checkout", "v1.4.0")
    after = [shop.order(s, [(LENS_KIT, 2)], "v1.4.0", check_cart=True) for s in shoppers]

    check(all(o.ok for o in base + after), "every order went through")
    check(all(o.cart_after == 0 for o in base), "v1.3.0: every cart is empty after checkout")
    check(
        all(o.cart_after for o in after if o.shopper.currency != "USD"),
        "v1.4.0: EUR and CAD carts still hold the ordered items",
    )
    check(
        all(o.cart_after == 0 for o in after if o.shopper.currency == "USD"),
        "v1.4.0: USD cart empty",
    )
    print("checking Jaeger")

    def emptied(spans: list[Span]) -> bool:
        return any(s.service == "checkout" and s.operation.endswith("EmptyCart") for s in spans)

    def placed(spans: list[Span]) -> bool:
        return any(s.service == "checkout" and s.operation.endswith("PlaceOrder") for s in spans)

    for o in after:
        # A missing span can't be waited for: wait for the order, then give stragglers 10s.
        spans = shop.spans(o.trace_id, until=lambda sp: emptied(sp) or placed(sp)) or []
        if not emptied(spans):
            time.sleep(10)
            spans = shop.spans(o.trace_id, wait=0) or []
        has_empty = emptied(spans)
        check(
            has_empty == (o.shopper.currency == "USD"),
            f"{o.shopper.currency} order: EmptyCart span {'present' if has_empty else 'missing'}",
        )
    first = next(o.at for o in after if o.shopper.n == 1)
    return {"around 10:40": f"around {first:%H:%M}", "this morning": part_of_day(first)}


def catalog(shop: Shop, check: Checks, a: argparse.Namespace) -> dict[str, str]:
    """Ticket 9: product-catalog v1.4.0 drops The Comet Book ($0.99) from the product listing."""
    ensure("product-catalog", "v1.3.0")
    before = {p["id"] for p in shop.products()}
    print(f"  v1.3.0 listing: {len(before)} products")
    pause(a.gap, "so the deploy stands apart in the metrics")
    deploy("product-catalog", "v1.4.0")
    after = {p["id"] for p in shop.products()}
    print(f"  v1.4.0 listing: {len(after)} products, missing {sorted(before - after)}")

    check(COMET_BOOK in before, "v1.3.0 lists The Comet Book")
    check(before - after == {COMET_BOOK}, "v1.4.0 lists every product except The Comet Book")
    check(shop.product_page(COMET_BOOK) == 200, "v1.4.0 still serves The Comet Book's own page")
    return {"this morning": part_of_day(datetime.now(UTC))}


SCENARIOS: dict[str, Scenario | None] = {
    "1": None,  # tickets 1, 2 and 7 need nothing in the shop
    "2": None,
    "3": amex,
    "4": expiry,
    "5": bulk_quote,
    "6": payment_flag,
    "7": None,
    "8": cart,
    "9": catalog,
    "cart": cart,  # the same scenarios by name
    "catalog": catalog,
}


def require_agent_db() -> None:
    """deploy.sh and flag.sh record into the agent's Postgres; fail before touching the shop."""
    import psycopg

    from app.settings import settings

    try:
        psycopg.connect(settings.database_url, connect_timeout=3).close()
    except psycopg.OperationalError as e:
        sys.exit(f"the agent's Postgres isn't reachable ({e}); run make db && make migrate")


def require_api() -> None:
    from app.settings import settings

    try:
        httpx.get(f"{settings.api_base_url}/simulator/templates", timeout=3).raise_for_status()
    except httpx.HTTPError:
        sys.exit(
            f"the agent API isn't up at {settings.api_base_url}; run make api, or use --no-send"
        )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("scenario", choices=SCENARIOS)
    p.add_argument("--no-send", action="store_true", help="print the ticket instead of sending it")
    p.add_argument(
        "--run-as-new", action="store_true", help="skip the duplicate check (a repeat demo run)"
    )
    p.add_argument("--gap", type=float, default=60, help="seconds between baseline and change")
    p.add_argument("--rounds", type=int, default=3, help="order rounds after the change")
    p.add_argument("--spacing", type=float, default=10, help="seconds between order rounds")
    p.add_argument("--shop", default=SHOP_URL, help="the shop's frontend proxy")
    a = p.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # interleave with deploy.sh's output

    run = SCENARIOS[a.scenario]
    ticket = template(a.scenario) if a.scenario.isdigit() else None
    if ticket and not a.no_send:
        require_api()
    replacements: dict[str, str] | None = {}
    if run:
        shop = Shop(a.shop)
        if not shop.reachable():
            sys.exit(f"the shop isn't up at {a.shop}; run make shop-up")
        require_agent_db()
        print(f"scenario {a.scenario}: {run.__doc__.splitlines()[0]}")
        check = Checks(shop)
        replacements = run(shop, check, a)
        print("traces:")
        for o in shop.orders:
            print(f"  {o.shopper.id} {o.at:%H:%M:%S} {o.phase:<8} {shop.trace_url(o.trace_id)}")
        if not check.passed:
            sys.exit(f"scenario {a.scenario} did not reproduce; no ticket sent")
        print(f"scenario {a.scenario} reproduced")

    if not ticket:
        return
    subject, body = ticket["subject"], ticket["body"]
    for phrase, value in (replacements or {}).items():
        if phrase not in subject + body:
            sys.exit(f"ticket {a.scenario} no longer says {phrase!r}; update scenario.py")
        subject, body = subject.replace(phrase, value), body.replace(phrase, value)
    if a.no_send:
        print(f"\nticket {a.scenario} (not sent)\n  subject: {subject}\n  body: {body}")
    else:
        send(subject, body, run_as_new=a.run_as_new)


if __name__ == "__main__":
    main()
