"""The codebox's helper commands (codebox/bin), run with bash against an exported index and a
checkout, the way the codebase analyst runs them; and their plain-search fallback."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.indexer import export
from app.settings import ROOT
from tests.test_indexer import CHARGE_JS, FILES, line_of, payment_index

BIN = ROOT / "codebox" / "bin"


@pytest.fixture
def box(tmp_path) -> tuple[Path, Path]:
    repo, index = tmp_path / "repo", tmp_path / "index"
    for path, text in FILES.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    export.write(index, [payment_index()], {"payment": "# payment\nCharges cards."})
    return repo, index


def run(repo: Path, index: Path, *cmd: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PATH": f"{BIN}:{os.environ['PATH']}", "INDEX_DIR": str(index)}
    return subprocess.run(
        ["bash", str(BIN / cmd[0]), *cmd[1:]], cwd=repo, env=env, capture_output=True, text=True
    )


def test_lookup_error_finds_a_message_by_its_text(box):
    out = run(*box, "lookup-error", "expired on").stdout
    assert f"src/payment/charge.js:{line_of(CHARGE_JS, 'expired on')} payment:" in out


def test_lookup_error_finds_the_template_from_a_message_it_produced(box):
    quoted = "The credit card (ending 4242) expired on 9/2026."
    out = run(*box, "lookup-error", quoted).stdout
    assert f"src/payment/charge.js:{line_of(CHARGE_JS, 'expired on')} payment:" in out
    assert "Credit card info is invalid" not in out


def test_lookup_error_finds_the_template_from_the_start_of_a_message(box):
    """Customers and analysts often quote only the start of a message the code produced."""
    out = run(*box, "lookup-error", "The credit card (ending 4242) expired").stdout
    assert f"src/payment/charge.js:{line_of(CHARGE_JS, 'expired on')} payment:" in out
    assert "not in the error index" not in out
    assert "not in the error index" in run(*box, "lookup-error", "The cart is empty").stdout


def test_lookup_error_treats_its_argument_as_text_not_a_pattern(box):
    result = run(*box, "lookup-error", "(ending")
    assert result.returncode == 0 and "expired on" in result.stdout, result.stderr


def test_repo_map_lists_one_service_with_signatures(box):
    out = run(*box, "repo-map", "payment").stdout
    assert "src/payment/index.js:3 function" in out
    assert "chargeServiceHandler" in out
    assert run(*box, "repo-map", "quote").stdout.strip() == "no symbols indexed for quote"


def test_find_symbol_gives_definitions_and_references(box):
    out = run(*box, "find-symbol", "chargeServiceHandler").stdout
    definitions, references = out.split("references:")
    assert "src/payment/index.js:3 payment function" in definitions
    assert "src/payment/" in references


def test_rpc_handler_takes_the_full_or_short_name(box):
    for name in ("PaymentService/Charge", "Charge"):
        assert run(*box, "rpc-handler", name).stdout.startswith("src/payment/index.js:")


def test_flag_reads(box):
    out = run(*box, "flag-reads", "paymentFailure").stdout
    assert out.startswith("src/payment/charge.js:") and "payment" in out


def test_a_missing_argument_is_a_usage_error(box):
    for cmd in ("lookup-error", "repo-map", "find-symbol", "rpc-handler", "flag-reads"):
        result = run(*box, cmd)
        assert result.returncode != 0 and "usage" in result.stderr, cmd


@pytest.mark.skipif(shutil.which("rg") is None, reason="needs ripgrep")
def test_without_an_index_the_helpers_fall_back_to_plain_search(box, tmp_path):
    repo, _ = box
    out = run(repo, tmp_path / "no-index", "lookup-error", "expired on").stdout
    assert out.startswith("(no code index; plain search)")
    assert f"src/payment/charge.js:{line_of(CHARGE_JS, 'expired on')}:" in out


# --- git in the codebox: /repo is the deployed tag, /prev the previous one ----------------------


def git(cwd: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def worktrees(tmp_path) -> dict[str, Path]:
    """A fork with two tags, checked out as two worktrees like the codebox's /repo and /prev."""
    main = tmp_path / "fork"
    main.mkdir()
    git(main, "init", "-q")
    for tag in ("v1.3.0", "v1.4.0"):
        (main / "charge.js").write_text(f"// {tag}\n")
        git(main, "add", ".")
        git(main, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", tag)
        git(main, "tag", tag)
    for tag in ("v1.3.0", "v1.4.0"):
        git(main, "worktree", "add", "-q", str(tmp_path / f"shop@{tag}"), tag)
    return {"main": main, "repo": tmp_path / "shop@v1.4.0", "prev": tmp_path / "shop@v1.3.0"}


def test_git_in_prev_uses_the_previous_tags_worktree(worktrees):
    meta = worktrees["main"] / ".git" / "worktrees"
    env = {
        **os.environ,
        "PATH": f"{BIN}:{os.environ['PATH']}",
        "GIT_DIR": str(meta / "shop@v1.4.0"),
        "GIT_WORK_TREE": str(worktrees["repo"]),
        "PREV_GIT_DIR": str(meta / "shop@v1.3.0"),
        "PREV_DIR": str(worktrees["prev"]),
    }
    tag = {t: git(worktrees["main"], "rev-parse", t) for t in ("v1.3.0", "v1.4.0")}
    assert git(worktrees["repo"], "rev-parse", "HEAD", env=env) == tag["v1.4.0"]
    assert git(worktrees["prev"], "rev-parse", "HEAD", env=env) == tag["v1.3.0"]
    assert (
        git(worktrees["repo"], "-C", "../shop@v1.3.0", "rev-parse", "HEAD", env=env)
        == (tag["v1.3.0"])
    )
    assert git(worktrees["prev"], "status", "--porcelain", env=env) == ""  # its own work tree
    assert git(worktrees["prev"], "log", "--format=%s", "-1", "--", "charge.js", env=env) == (
        "v1.3.0"
    )
