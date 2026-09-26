"""Stable help-center sections, one citation ID per Markdown heading."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HelpSection:
    id: str
    title: str
    body: str
    content_hash: str


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def chunk_markdown(path: Path, markdown: str) -> list[HelpSection]:
    """Split at ##, keeping the article title and section heading in each stored body."""
    lines = markdown.splitlines()
    titles = [line[2:].strip() for line in lines if line.startswith("# ")]
    if len(titles) != 1:
        raise ValueError(f"{path}: expected one # article title")
    article_title = titles[0]
    sections: list[HelpSection] = []
    heading: str | None = None
    body: list[str] = []
    seen: dict[str, int] = {}

    def flush() -> None:
        if heading is None:
            return
        clean = "\n".join(body).strip()
        if not clean:
            raise ValueError(f"{path}: empty section {heading}")
        base = _slug(heading)
        seen[base] = seen.get(base, 0) + 1
        suffix = f"-{seen[base]}" if seen[base] > 1 else ""
        text = f"{article_title}\n{heading}\n{clean}"
        sections.append(
            HelpSection(
                id=f"{path.stem}#{base}{suffix}",
                title=f"{article_title} — {heading}",
                body=text,
                content_hash=content_hash(text),
            )
        )

    for line in lines:
        if line.startswith("## "):
            flush()
            heading = line[3:].strip()
            body = []
        elif heading is not None:
            body.append(line)
    flush()
    if not sections:
        raise ValueError(f"{path}: no ## sections")
    return sections
