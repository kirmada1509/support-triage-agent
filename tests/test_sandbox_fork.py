"""The shop fork (make sandbox): pinned to upstream, v1.3.0 is upstream plus the sandbox setup,
and v1.4.0 plants exactly the four bugs, where the codebase analyst will find them with git.

Run with `make test-sandbox`. Reads the fork at SANDBOX_DIR (default ../opentelemetry-demo)
and, where Docker is available, the images built from it.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from app.settings import ROOT

pytestmark = pytest.mark.sandbox

SANDBOX = Path(os.environ.get("SANDBOX_DIR", ROOT.parent / "opentelemetry-demo")).resolve()
KIT = ROOT / "sandbox"
ENV = dict(
    line.split("=", 1)
    for line in (KIT / "upstream.env").read_text().splitlines()
    if line and not line.startswith("#")
)
PIN = ENV["UPSTREAM_SHA"]
VERSIONED = ("payment", "quote", "checkout", "product-catalog")

# The v1.4.0 commits, oldest first: subject -> the files it changes.
V1_4_0 = {
    "docs(payment): describe the charge rules": {"src/payment/README.md"},
    "perf: batch quote calculation for large orders": {"src/quote/app/routes.php"},
    "chore(checkout): log the order currency with each placed order": {"src/checkout/main.go"},
    "refactor: simplify card expiry comparison": {"src/payment/charge.js"},
    "chore(quote): include the item count in the quote log": {"src/quote/app/routes.php"},
    "chore: tidy up post-order cleanup": {"src/checkout/main.go"},
    "chore(payment): give declined-charge logs a message": {"src/payment/index.js"},
    "feat: hide unpriced products from the catalog listing": {"src/product-catalog/main.go"},
}

# Each planted bug: the commit, and a line of it at v1.4.0 (as sandbox/README.md cites it).
BUGS = [
    (
        "refactor: simplify card expiry comparison",
        "src/payment/charge.js",
        88,
        "    if (currentPeriod >= expiryPeriod) {",
    ),
    (
        "perf: batch quote calculation for large orders",
        "src/quote/app/routes.php",
        37,
        "                $quote += round(array_sum($batch), 2);",
    ),
    (
        "chore: tidy up post-order cleanup",
        "src/checkout/main.go",
        545,
        '\tif req.UserCurrency != "USD" {',
    ),
    (
        "feat: hide unpriced products from the catalog listing",
        "src/product-catalog/main.go",
        235,
        "\t\tWHERE p.price_units > 0",
    ),
]


@pytest.fixture(scope="module", autouse=True)
def fork():
    if not (SANDBOX / ".git").exists():
        pytest.fail(f"no fork at {SANDBOX}; run make sandbox (or set SANDBOX_DIR)")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(SANDBOX), *args], capture_output=True, text=True, check=True
    ).stdout


def lines(tag: str, path: str) -> list[str]:
    return git("show", f"{tag}:{path}").splitlines()


def blamed(tag: str, path: str, start: int, end: int) -> set[str]:
    """The commits that last changed lines start..end of path at tag."""
    out = git("blame", "--porcelain", "-L", f"{start},{end}", tag, "--", path)
    return {m for m in re.findall(r"^([0-9a-f]{40}) \d+ \d+", out, re.M)}


def subject(sha: str) -> str:
    return git("log", "-1", "--format=%s", sha).strip()


# --- tags and history ---------------------------------------------------------------------------


def test_tags_are_where_the_kit_says():
    assert git("rev-parse", "--short=8", "v1.3.0").strip() == ENV["EXPECTED_V1_3_0"]
    assert git("rev-parse", "--short=8", "v1.4.0").strip() == ENV["EXPECTED_V1_4_0"]
    git("merge-base", "--is-ancestor", PIN, "v1.3.0")  # raises if the pin isn't under v1.3.0
    assert git("rev-list", "--count", f"{PIN}..v1.3.0").strip() == "2"
    assert git("rev-list", "--count", "v1.3.0..v1.4.0").strip() == "8"


def test_no_upstream_version_tags():
    tags = set(git("tag", "-l").split())
    assert {"v1.3.0", "v1.4.0"} <= tags
    assert not tags & {"1.3.0", "1.4.0"}, "upstream's 1.3.0/1.4.0 sit one typo from ours"


def test_v1_3_0_is_upstream_plus_the_sandbox_setup():
    changed = set(git("diff", "--name-only", PIN, "v1.3.0").split())
    assert changed == {
        ".env.override",
        "compose.extras.yaml",
        "compose.versions.yaml",
        "src/postgresql/init.sql",
    }


def test_overlay_files_are_the_kit_s():
    for f in (KIT / "overlay").rglob("*"):
        if f.is_file():
            path = f.relative_to(KIT / "overlay").as_posix()
            assert git("show", f"v1.3.0:{path}") == f.read_text(), path


def test_read_only_role_is_in_both_versions():
    for tag in ("v1.3.0", "v1.4.0"):
        sql = "\n".join(lines(tag, "src/postgresql/init.sql"))
        assert "CREATE ROLE agent_ro WITH LOGIN" in sql
        assert "GRANT SELECT ON ALL TABLES IN SCHEMA catalog TO agent_ro;" in sql
        assert "ALTER ROLE agent_ro SET default_transaction_read_only = on;" in sql
        assert not re.search(r"GRANT (INSERT|UPDATE|DELETE|ALL)[^;]*TO agent_ro", sql)


def test_v1_4_0_commits_and_the_files_they_touch():
    log = git("log", "--reverse", "--format=%H %s", "v1.3.0..v1.4.0").splitlines()
    assert [line.split(" ", 1)[1] for line in log] == list(V1_4_0)
    for line in log:
        sha, title = line.split(" ", 1)
        files = set(git("show", "--name-only", "--format=", sha).split())
        assert files == V1_4_0[title], title


# --- the planted bugs ---------------------------------------------------------------------------


@pytest.mark.parametrize(("title", "path", "line", "text"), BUGS, ids=lambda v: str(v)[:24])
def test_bug_is_planted_by_its_commit(title, path, line, text):
    assert lines("v1.4.0", path)[line - 1] == text
    assert text.strip() not in "\n".join(lines("v1.3.0", path))
    assert {subject(c) for c in blamed("v1.4.0", path, line, line)} == {title}


def test_expiry_bug_diff():
    diff = git("diff", "v1.3.0", "v1.4.0", "--", "src/payment/charge.js")
    assert "-    if ((currentYear * 12 + currentMonth) > (year * 12 + month)) {" in diff
    assert "+    if (currentPeriod >= expiryPeriod) {" in diff
    assert (
        lines("v1.3.0", "src/payment/charge.js")[85]
        .strip()
        .startswith("if ((currentYear * 12 + currentMonth) > (year * 12 + month))")
    )  # line 86, as the plan cites it


def test_cart_bug_empties_only_usd_carts():
    go = lines("v1.4.0", "src/checkout/main.go")
    assert go[380] == "\tcs.cleanUpAfterOrder(ctx, req)"  # where emptyUserCart was called
    fn = "\n".join(go[543:554])  # cleanUpAfterOrder, lines 544-554
    assert fn.index("return") < fn.index("cs.emptyUserCart(ctx, req.UserId)")
    assert lines("v1.3.0", "src/checkout/main.go")[380] == "\t_ = cs.emptyUserCart(ctx, req.UserId)"


def test_quote_bug_adds_to_the_existing_total():
    php = "\n".join(lines("v1.4.0", "src/quote/app/routes.php"))
    total = php.index("$quote = round($costPerItem * $numberOfItems, 2);")
    batch = php.index("if ($numberOfItems > LARGE_ORDER_BATCH_SIZE)")
    assert total < batch and "$quote = 0" not in php[total:]  # never reset before the batches


def test_amex_rule_is_upstream_and_unchanged():
    """Ticket 3 is a false positive only if the card-type check (lines 82-84) is upstream's."""
    js = lines("v1.4.0", "src/payment/charge.js")
    assert "Only VISA or MasterCard is accepted" in js[82]
    ours = set(git("rev-list", f"{PIN}..v1.4.0").split())
    assert not blamed("v1.4.0", "src/payment/charge.js", 82, 84) & ours


def test_harmless_readme_contradicts_the_expiry_bug():
    readme = "\n".join(lines("v1.4.0", "src/payment/README.md"))
    assert "valid through the last day of its expiration month" in readme


def test_readme_cites_each_bug_where_it_is():
    """sandbox/README.md's `src/...:N` (or `:N-M`) for each bug covers the bug's line."""
    refs = re.findall(r"`(src/[\w/.-]+):(\d+)(?:-(\d+))?`", (KIT / "README.md").read_text())
    cited = {(path, int(start), int(end or start)) for path, start, end in refs}
    for _, path, line, _ in BUGS:
        assert any(p == path and a <= line <= b for p, a, b in cited), f"{path}:{line}"


# --- what was built from it ---------------------------------------------------------------------


def test_worktrees_are_at_their_tags():
    for tag in ("v1.3.0", "v1.4.0"):
        wt = SANDBOX.parent / f"shop@{tag}"
        if not wt.exists():
            pytest.skip(f"no worktree {wt}; ./sandbox/build-images.sh creates it")
        head = subprocess.run(
            ["git", "-C", str(wt), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout
        assert head == git("rev-parse", f"{tag}^{{commit}}")


def test_images_are_built_from_their_tags():
    if not shutil.which("docker"):
        pytest.skip("no docker")
    for tag in ("v1.3.0", "v1.4.0"):
        sha = git("rev-parse", f"{tag}^{{commit}}").strip()
        for service in VERSIONED:
            r = subprocess.run(
                [
                    "docker",
                    "image",
                    "inspect",
                    "-f",
                    '{{ index .Config.Labels "org.opencontainers.image.revision" }}',
                    f"sandbox/{service}:{tag}",
                ],
                capture_output=True,
                text=True,
            )
            assert r.returncode == 0, f"no image sandbox/{service}:{tag}; make sandbox-images"
            assert r.stdout.strip() == sha, f"sandbox/{service}:{tag} is stale; make sandbox-images"
