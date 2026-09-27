"""Copy short engineering excerpts from successful codebox output tied to checked code evidence."""

import re

from pydantic import ValidationError

from app.events import CodeOut, DiffOut, ModelOutputEvent, StoredEvent, TerminalOut, ToolCallEvent
from app.models import CodeSnippet, Findings, ToolRecord

DIFF_FILE = re.compile(r"^diff --git a/(\S+) b/(\S+)$", re.MULTILINE)
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)
SOURCE = re.compile(
    r"(?:cd /repo && )?sed -n '(\d+),(\d+)p' (?:/repo/)?(src/[\w./-]+\.(?:js|ts|py|go|cs))"
)
REFERENCE = re.compile(r"^(src/[\w./-]+):(\d+)(?:-\d+)?$")
LANGUAGE = {"js": "javascript", "ts": "typescript", "py": "python", "go": "go", "cs": "csharp"}
MAX_LINES = 20
MAX_SNIPPETS = 2


def _diff(call: ToolRecord, path: str, line: int) -> CodeSnippet | None:
    text = call.output
    matches = list(DIFF_FILE.finditer(text))
    for index, match in enumerate(matches):
        if match.group(1) != path or match.group(2) != path:
            continue
        block = text[
            match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(text)
        ]
        hunks = list(HUNK.finditer(block))
        for hunk_index, hunk in enumerate(hunks):
            start = int(hunk.group(1))
            count = int(hunk.group(2) or 1)
            end = start + count - 1
            if not start - 3 <= line <= end + 3:
                continue
            excerpt = block[
                hunk.start() : hunks[hunk_index + 1].start()
                if hunk_index + 1 < len(hunks)
                else len(block)
            ].rstrip("\n")
            lines = excerpt.splitlines()
            if len(lines) > MAX_LINES:
                continue
            if not any(item.startswith("+") and not item.startswith("+++") for item in lines):
                continue
            return CodeSnippet(
                render="diff",
                file=path,
                language="diff",
                start_line=start,
                end_line=end,
                content=excerpt,
                call_id=call.call_id,
            )
    return None


def _source(call: ToolRecord, path: str, line: int) -> CodeSnippet | None:
    command = str(call.args.get("command", ""))
    match = SOURCE.fullmatch(command.strip())
    if not match or match.group(3) != path or not call.output.strip():
        return None
    start, end = int(match.group(1)), int(match.group(2))
    if not start <= line <= end or end - start + 1 > MAX_LINES:
        return None
    content = call.output.rstrip("\n")
    if len(content.splitlines()) != end - start + 1:
        return None
    return CodeSnippet(
        render="code",
        file=path,
        language=LANGUAGE[path.rsplit(".", 1)[-1]],
        start_line=start,
        end_line=end,
        content=content,
        call_id=call.call_id,
    )


def extract_snippets(findings: Findings, calls: list[ToolRecord]) -> list[CodeSnippet]:
    """Only checked code references may select exact text from successful bash output."""
    if findings.agent != "codebase_analyst":
        return []
    refs = []
    for evidence in findings.evidence:
        match = REFERENCE.fullmatch(evidence.ref) if evidence.source == "code" else None
        if match:
            refs.append((match.group(1), int(match.group(2))))
    snippets = []
    for path, line in refs:
        for extractor in (_diff, _source):
            for call in calls:
                if call.ok and call.tool == "bash":
                    snippet = extractor(call, path, line)
                    if snippet and not any(
                        prior.render == snippet.render and prior.file == snippet.file
                        for prior in snippets
                    ):
                        snippets.append(snippet)
                        break
            if len(snippets) >= MAX_SNIPPETS:
                return snippets
    return snippets


def select_snippets(file_line: str | None, findings: list[Findings]) -> list[CodeSnippet]:
    """Only show excerpts surrounding the checked location in the final verdict."""
    match = REFERENCE.fullmatch(file_line or "")
    if not match:
        return []
    path, line = match.group(1), int(match.group(2))
    selected = []
    for finding in sorted(findings, key=lambda item: item.round, reverse=True):
        for snippet in finding.code_snippets:
            if snippet.file == path and snippet.start_line - 3 <= line <= snippet.end_line + 3:
                if not any(item.content == snippet.content for item in selected):
                    selected.append(snippet)
                if len(selected) >= MAX_SNIPPETS:
                    return selected
    return selected


def snippets_from_events(file_line: str | None, events: list[StoredEvent]) -> list[CodeSnippet]:
    """Recover excerpts for old stored runs using their checked Findings and tool outputs."""
    if not REFERENCE.fullmatch(file_line or ""):
        return []
    # round2 is the code follow-up's stage name in runs stored before the two-way handoff
    calls: dict[str, list[ToolRecord]] = {"codebase_analyst": [], "code_followup": [], "round2": []}
    found: list[tuple[str, Findings]] = []
    for item in events:
        event = item.event
        if (
            isinstance(event, ToolCallEvent)
            and event.stage in calls
            and event.tool == "bash"
            and event.status == "ok"
        ):
            output = event.output
            raw = event.raw_output or (
                output.output
                if isinstance(output, TerminalOut)
                else output.code
                if isinstance(output, CodeOut)
                else output.diff
                if isinstance(output, DiffOut)
                else ""
            )
            calls[event.stage].append(
                ToolRecord(
                    call_id=event.call_id,
                    tool=event.tool,
                    args=event.args,
                    output=raw,
                )
            )
        elif isinstance(event, ModelOutputEvent) and event.name == "Findings":
            if event.stage not in calls:
                continue
            try:
                finding = Findings.model_validate(event.data)
            except ValidationError:
                continue
            found.append((event.stage, finding))
    enriched = [
        finding.model_copy(
            update={
                "code_snippets": finding.code_snippets or extract_snippets(finding, calls[stage])
            }
        )
        for stage, finding in found
    ]
    return select_snippets(file_line, enriched)
