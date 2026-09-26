"""A service's code index at one commit of the fork, read straight from git (no checkout)."""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app.indexer import extract


@dataclass
class CodeIndex:
    service: str
    git_sha: str
    symbols: list[extract.Symbol] = field(default_factory=list)
    errors: list[extract.ErrorString] = field(default_factory=list)
    flags: list[extract.FlagRead] = field(default_factory=list)
    rpcs: list[extract.Rpc] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)  # source files, for the service card


def build_index(service: str, git_sha: str, files: dict[str, str], proto: str) -> CodeIndex:
    """files: every file under the service's path at that commit; proto: the shared .proto."""
    go_keys: dict[str, str] = {}
    for path, text in files.items():
        if path.endswith(".go") and "flags" in Path(path).parts:
            go_keys |= extract.go_flag_keys(text)
    source = {p: t for p, t in files.items() if extract.is_source(p, t)}
    index = CodeIndex(service, git_sha, files=source)
    for path, text in sorted(source.items()):
        lang = extract.language(path)
        index.symbols += extract.symbols(path, text, lang)
        index.errors += extract.error_strings(path, text, lang)
        index.flags += extract.flag_reads(path, text, lang, go_keys)
    index.rpcs = extract.rpc_handlers(source, extract.proto_methods(proto))
    return index


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


def resolve(repo: Path, rev: str) -> str:
    return _git(repo, "rev-parse", "--verify", f"{rev}^{{commit}}").strip()


def read_tree(repo: Path, sha: str, path: str, suffixes: tuple[str, ...] = ()) -> dict[str, str]:
    """Files under path at a commit: the ones the indexer can parse, or with these suffixes."""
    names = _git(repo, "ls-tree", "-r", "--name-only", sha, "--", path).split("\n")
    wanted = [n for n in names if n and (n.endswith(suffixes) if suffixes else extract.language(n))]
    return {n: _git(repo, "show", f"{sha}:{n}") for n in wanted}


def index_at(repo: Path, service: str, path: str, rev: str) -> CodeIndex:
    sha = resolve(repo, rev)
    proto = "\n".join(read_tree(repo, sha, "pb", (".proto",)).values())
    return build_index(service, sha, read_tree(repo, sha, path), proto)


def change_summary(repo: Path, path: str, previous: str, rev: str) -> str:
    """Commits and changed files under a service's path since the previous deploy."""
    log = _git(repo, "log", "--format=%h %s", f"{previous}..{rev}", "--", path).strip()
    stat = _git(repo, "diff", "--stat", previous, rev, "--", path).strip()
    if not log:
        return f"no changes under {path} between {previous} and {rev}"
    return f"commits {previous}..{rev} under {path}:\n{log}\n\n{stat}"
