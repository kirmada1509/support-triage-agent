"""The running shop (make shop-up): every scenario reproduces for real and is checked in
Jaeger, deploys are recorded, and the data the analysts will read is where they'll look.

Run with `make test-shop`, which records deploys into a throwaway triage_test database. Takes a
few minutes; leaves every versioned service on v1.4.0 and the paymentFailure flag off.
"""

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg
import pytest
from sqlalchemy.engine import make_url

from app.settings import ROOT, settings

pytestmark = pytest.mark.shop

SANDBOX = Path(os.environ.get("SANDBOX_DIR", ROOT.parent / "opentelemetry-demo")).resolve()
SHOP = os.environ.get("SHOP_URL", "http://localhost:8080")
PROMETHEUS = "http://localhost:9090"


@pytest.fixture(scope="module", autouse=True)
def shop_is_up():
    if not (make_url(settings.database_url).database or "").endswith("_test"):
        pytest.fail("DATABASE_URL must name a database ending in _test (make test-shop)")
    try:
        httpx.get(f"{SHOP}/api/products", timeout=5).raise_for_status()
    except httpx.HTTPError:
        pytest.fail(f"the shop isn't up at {SHOP}; run make shop-up")
    yield
    # scenario 6 leaves the flag at 25%: turn it off and leave the fork clean
    subprocess.run(
        [ROOT / "scenarios" / "flag.sh", "paymentFailure", "off"],
        env={**os.environ, "FLAG_RECORD": "0"},
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(SANDBOX), "checkout", "--", "src/flagd"], check=False)


def compose(*args: str) -> str:
    return subprocess.run(
        [ROOT / "sandbox" / "compose.sh", *args], capture_output=True, text=True, check=True
    ).stdout


def test_versioned_services_run_the_sandbox_images():
    rows = [json.loads(line) for line in compose("ps", "--format", "json").splitlines()]
    by_service = {r["Service"]: r for r in rows}
    assert len(by_service) >= 25, sorted(by_service)
    assert all(r["State"] == "running" for r in rows), [r["Service"] for r in rows]
    for service in ("payment", "quote", "checkout", "product-catalog"):
        assert by_service[service]["Image"].startswith(f"sandbox/{service}:v1.")
    assert by_service["frontend"]["Image"].endswith(":3.1.0-frontend")


# Demo order; 6 last, because its failed charges would muddy the others.
@pytest.mark.parametrize("name", ["3", "4", "5", "cart", "catalog", "6"])
def test_scenario_reproduces(name):
    r = subprocess.run(
        [
            sys.executable,
            ROOT / "scenarios" / "scenario.py",
            name,
            "--no-send",
            "--gap",
            "10",
            "--rounds",
            "1",
            "--spacing",
            "3",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert r.returncode == 0 and f"scenario {name} reproduced" in r.stdout, r.stdout + r.stderr
    assert not re.search(r"^  FAIL  ", r.stdout, re.M)  # no failed check (declined orders are fine)


def test_deploys_were_recorded_with_their_commits():
    with psycopg.connect(settings.database_url) as conn:
        rows = conn.execute(
            "SELECT DISTINCT ON (service) service, previous_version, version, commit_titles"
            " FROM deploys ORDER BY service, deployed_at DESC"
        ).fetchall()
    deploys = {r[0]: r[1:] for r in rows}
    assert deploys["payment"][:2] == ("v1.3.0", "v1.4.0")
    assert "refactor: simplify card expiry comparison" in deploys["payment"][2]
    assert "perf: batch quote calculation for large orders" in deploys["quote"][2]
    assert set(deploys) == {"payment", "quote", "checkout", "product-catalog"}


def test_span_metrics_carry_the_deployed_version():
    query = 'count by (service_version) (traces_span_metrics_calls_total{service_name="payment"})'
    r = httpx.get(f"{PROMETHEUS}/api/v1/query", params={"query": query}, timeout=10).json()
    versions = {x["metric"].get("service_version") for x in r["data"]["result"]}
    assert "v1.4.0" in versions, versions


def test_logs_land_in_the_daily_index():
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    out = subprocess.run(
        [
            "docker",
            "exec",
            "opensearch",
            "curl",
            "-s",
            "localhost:9200/_cat/indices/otel-logs-*?h=index",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert f"otel-logs-{today}" in out.split()


@pytest.mark.parametrize(
    ("sql", "error"),
    [
        ("UPDATE catalog.products SET price_units = 1", "read-only transaction"),
        (
            "SET TRANSACTION READ WRITE; UPDATE catalog.products SET price_units = 1",
            "permission denied",
        ),
        ('SELECT count(*) FROM accounting."order"', "permission denied"),
        ("CREATE TABLE catalog.x (id int)", "read-only transaction"),
    ],
)
def test_agent_ro_cannot_write(sql, error):
    r = psql(sql)
    assert r.returncode != 0 and error in r.stderr


def test_agent_ro_reads_the_catalog():
    r = psql("SELECT count(*), count(*) FILTER (WHERE price_units = 0) FROM catalog.products")
    assert r.returncode == 0 and r.stdout.strip() == "10|1"  # The Comet Book is the $0.99 one


def psql(sql: str) -> subprocess.CompletedProcess:
    url = "postgresql://agent_ro:agent_ro_password@localhost/astronomy_db"
    return subprocess.run(
        ["docker", "exec", "astronomy-db", "psql", url, "-At", "-c", sql],
        capture_output=True,
        text=True,
    )
