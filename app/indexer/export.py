"""The code index as plain files for the codebase analyst's container, which has no network:
the helper commands in codebox/bin read these from /index (mounted read-only).

  symbols.tsv  file, line, service, kind, name, signature
  errors.tsv   file, line, service, message, regex matching the messages it produces
  rpc.tsv      Service/Method, handler file, line, service
  flags.tsv    flag, file, line, service
  cards/<service>.md
"""

from pathlib import Path

from app.indexer.build import CodeIndex
from app.indexer.extract import template_pattern


def _row(*values) -> str:
    return "\t".join(" ".join(str(v).split()) for v in values)


def write(out: Path, indexes: list[CodeIndex], cards: dict[str, str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    tables = {
        "symbols.tsv": [
            _row(s.file, s.line, i.service, s.kind, s.name, s.signature)
            for i in indexes
            for s in i.symbols
        ],
        "errors.tsv": [
            _row(e.file, e.line, i.service, e.text, template_pattern(" ".join(e.text.split())))
            for i in indexes
            for e in i.errors
        ],
        "rpc.tsv": [_row(r.method, r.file, r.line, i.service) for i in indexes for r in i.rpcs],
        "flags.tsv": [_row(f.flag, f.file, f.line, i.service) for i in indexes for f in i.flags],
    }
    for name, rows in tables.items():
        (out / name).write_text("".join(f"{r}\n" for r in rows))
    (out / "cards").mkdir(exist_ok=True)
    for service, text in cards.items():
        (out / "cards" / f"{service}.md").write_text(text)
