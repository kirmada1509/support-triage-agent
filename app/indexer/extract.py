"""What the code index holds, extracted from source text with ast-grep (tree-sitter): symbols
with signatures, error and log messages, feature-flag reads and gRPC handlers. Pure functions of
the text; app/indexer/build.py reads the files from git. Lines are 1-based.
"""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from ast_grep_py import SgNode, SgRoot

LANGUAGES = {
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".go": "go",
    ".php": "php",
    ".py": "python",
}
SKIP_DIRS = {"node_modules", "vendor", "genproto", "test", "tests", "__tests__"}
SKIP_SUFFIXES = ("_test.go", ".test.js", ".spec.js", ".test.ts", ".spec.ts")
MAX_SIGNATURE = 200


@dataclass(frozen=True)
class Symbol:
    file: str
    line: int
    kind: str  # function | method | class | struct | interface
    name: str
    signature: str


@dataclass(frozen=True)
class ErrorString:
    file: str
    line: int
    text: str


@dataclass(frozen=True)
class FlagRead:
    file: str
    line: int
    flag: str


@dataclass(frozen=True)
class Rpc:
    method: str  # Service/Method, as in the proto
    file: str
    line: int


def language(path: str) -> str | None:
    return LANGUAGES.get(PurePosixPath(path).suffix)


def is_source(path: str, source: str) -> bool:
    """Hand-written, non-test code: what the analysts should read and the index should hold."""
    p = PurePosixPath(path)
    if language(path) is None or SKIP_DIRS & set(p.parts) or p.name.endswith(SKIP_SUFFIXES):
        return False
    head = "\n".join(source.splitlines()[:5])
    return "Code generated" not in head and "DO NOT EDIT" not in head


def _line(node: SgNode) -> int:
    return node.range().start.line + 1


def _signature(node: SgNode) -> str:
    """The declaration without its body, on one line."""
    body = node.field("body")
    text = node.text()
    if body is not None:
        text = text[: body.range().start.index - node.range().start.index]
    else:
        text = text.splitlines()[0]
    text = " ".join(text.split()).rstrip(" {=>")
    return text[:MAX_SIGNATURE]


# tree-sitter node kind -> symbol kind, per language
_DECLARATIONS = {
    "javascript": {
        "function_declaration": "function",
        "generator_function_declaration": "function",
        "method_definition": "method",
        "class_declaration": "class",
    },
    "go": {"function_declaration": "function", "method_declaration": "method"},
    "php": {
        "function_definition": "function",
        "method_declaration": "method",
        "class_declaration": "class",
        "interface_declaration": "interface",
    },
    "python": {"function_definition": "function", "class_definition": "class"},
}
_DECLARATIONS["typescript"] = _DECLARATIONS["javascript"] | {"interface_declaration": "interface"}
_FUNCTION_VALUES = {"arrow_function", "function_expression", "function"}


def symbols(file: str, source: str, lang: str) -> list[Symbol]:
    root = SgRoot(source, lang).root()
    found: list[Symbol] = []
    for node_kind, kind in _DECLARATIONS.get(lang, {}).items():
        for node in root.find_all(kind=node_kind):
            name = node.field("name")
            if name is not None:
                found.append(Symbol(file, _line(node), kind, name.text(), _signature(node)))
    if lang in ("javascript", "typescript"):
        # const f = () => {...}  and  module.exports.f = async x => {...}
        for node_kind, name_field, value_field in (
            ("variable_declarator", "name", "value"),
            ("assignment_expression", "left", "right"),
        ):
            for node in root.find_all(kind=node_kind):
                name, value = node.field(name_field), node.field(value_field)
                if name is None or value is None or value.kind() not in _FUNCTION_VALUES:
                    continue
                sig = " ".join(node.text()[: _body_offset(node, value)].split()).rstrip(" {=>")
                found.append(Symbol(file, _line(node), "function", name.text().split(".")[-1], sig))
    if lang == "go":
        for spec in root.find_all(kind="type_spec"):
            name, typ = spec.field("name"), spec.field("type")
            if (
                name is not None
                and typ is not None
                and typ.kind()
                in (
                    "struct_type",
                    "interface_type",
                )
            ):
                kind = "struct" if typ.kind() == "struct_type" else "interface"
                found.append(Symbol(file, _line(spec), kind, name.text(), f"type {name.text()}"))
    return sorted(set(found), key=lambda s: (s.line, s.name))


def _body_offset(node: SgNode, value: SgNode) -> int:
    body = value.field("body")
    end = body.range().start.index if body is not None else value.range().end.index
    return min(end - node.range().start.index, MAX_SIGNATURE)


# --- error and log messages -------------------------------------------------------------------

# Call nodes per language: (node kind, callee field or None for the first named child).
_CALLS = {
    "javascript": [("call_expression", "function"), ("new_expression", "constructor")],
    "go": [("call_expression", "function")],
    "php": [
        ("object_creation_expression", None),
        ("member_call_expression", "name"),
        ("scoped_call_expression", "name"),
        ("function_call_expression", "function"),
    ],
    "python": [("call", "function")],
}
_CALLS["typescript"] = _CALLS["javascript"]
_ERROR_FUNCTIONS = {"status.Errorf", "status.Error", "fmt.Errorf", "errors.New"}
_LOG_METHODS = {
    "error", "warn", "warning", "fatal", "critical", "exception",
    "Error", "Errorf", "Warn", "Warnf", "Fatal", "Fatalf", "Panicf",
}  # fmt: skip
_STRING_KINDS = {
    "string",
    "template_string",
    "interpreted_string_literal",
    "raw_string_literal",
    "encapsed_string",
}


def _calls(root: SgNode, lang: str):
    """(callee text, argument nodes) for every call or `new` in a file."""
    for kind, callee_field in _CALLS.get(lang, []):
        for node in root.find_all(kind=kind):
            named = [c for c in node.children() if c.is_named()]
            callee = node.field(callee_field) if callee_field else (named[0] if named else None)
            args = node.field("arguments") or next(
                (c for c in named if c.kind() in ("arguments", "argument_list")), None
            )
            if callee is not None and args is not None:
                yield kind, callee.text(), [c for c in args.children() if c.is_named()]


def _literal(node: SgNode) -> SgNode | None:
    """The string literal an argument is, or wraps (PHP arguments, Go fmt.Sprintf)."""
    if node.kind() == "argument":  # PHP wraps each argument
        node = next((c for c in node.children() if c.is_named()), node)
    if node.kind() == "call_expression" and node.text().startswith("fmt.Sprintf("):
        args = node.field("arguments")
        first = next((c for c in args.children() if c.is_named()), None) if args else None
        node = first or node
    return node if node.kind() in _STRING_KINDS else None


def _is_error_call(kind: str, callee: str) -> bool:
    if kind in ("new_expression", "object_creation_expression"):
        return bool(re.search(r"(Error|Exception)$", callee))
    last = re.split(r"\.|->|::", callee)[-1]
    return (
        callee in _ERROR_FUNCTIONS
        or last in _LOG_METHODS
        or bool(re.search(r"(Error|Exception)$", last))
    )


def error_strings(file: str, source: str, lang: str) -> list[ErrorString]:
    """Literal messages given to errors, exceptions and error or warning logs (the first string
    among the first two arguments: loggers often take a context object first)."""
    root = SgRoot(source, lang).root()
    found: set[ErrorString] = set()
    for kind, callee, args in _calls(root, lang):
        if not _is_error_call(kind, callee):
            continue
        literal = next((lit for a in args[:2] if (lit := _literal(a)) is not None), None)
        if literal is None:
            continue
        text = literal.text()[1:-1].strip()
        if text:
            found.add(ErrorString(file, _line(literal), text))
    return sorted(found, key=lambda e: (e.line, e.text))


def template_pattern(text: str) -> str:
    """A regex that matches the messages a template produces: JS ${...}, Go %v, PHP {$x} or $x
    stand for any text."""
    placeholder = re.compile(r"\$\{[^}]*\}|%[-+# 0-9.]*[a-zA-Z]|\{\$[^}]*\}|\$[a-zA-Z_]\w*")
    parts, last = [], 0
    for m in placeholder.finditer(text):
        parts.append(re.escape(text[last : m.start()]))
        parts.append(".*?")
        last = m.end()
    parts.append(re.escape(text[last:]))
    return "".join(parts)


# --- feature flags ------------------------------------------------------------------------------

_FLAG_GETTERS = {
    "getBooleanValue", "getNumberValue", "getStringValue", "getObjectValue",
    "getBooleanDetails", "getNumberDetails", "getStringDetails", "getObjectDetails",
    "BooleanValue", "IntValue", "FloatValue", "StringValue", "ObjectValue",
    "Boolean", "Int", "Float", "String", "Object",
}  # fmt: skip


def go_flag_keys(flags_gen: str) -> dict[str, str]:
    """Generated Go flag accessors (flags.PaymentUnreachable) -> flag keys (paymentUnreachable)."""
    pattern = re.compile(r'var\s+(\w+)\s*=\s*struct\b.*?stringer\("([^"]+)"\)', re.DOTALL)
    return dict(pattern.findall(flags_gen))


def flag_reads(file: str, source: str, lang: str, go_keys: dict[str, str]) -> list[FlagRead]:
    root = SgRoot(source, lang).root()
    found: set[FlagRead] = set()
    if lang in ("javascript", "typescript", "go"):
        for match in root.find_all(pattern="$C.$M($$$ARGS)"):
            if match.get_match("M").text() not in _FLAG_GETTERS:
                continue
            args = [a for a in match.get_multiple_matches("ARGS") if a.is_named()]
            keys = [a for a in args[:2] if a.kind() in _STRING_KINDS]
            if keys and (lang != "go" or len(args) >= 3):
                found.add(FlagRead(file, _line(match), keys[0].text()[1:-1]))
    if lang == "go":
        for match in root.find_all(pattern="flags.$F.$V($$$)"):
            if match.get_match("V").text() in ("Value", "ValueWithDetails"):
                if key := go_keys.get(match.get_match("F").text()):
                    found.add(FlagRead(file, _line(match), key))
    return sorted(found, key=lambda f: (f.line, f.flag))


# --- gRPC ---------------------------------------------------------------------------------------


def proto_methods(proto: str) -> list[str]:
    """Service/Method for every rpc in a .proto file, in order."""
    methods = []
    for m in re.finditer(r"\bservice\s+(\w+)\s*\{", proto):
        depth, i = 1, m.end()
        while depth and i < len(proto):
            depth += {"{": 1, "}": -1}.get(proto[i], 0)
            i += 1
        body = proto[m.end() : i]
        methods += [f"{m.group(1)}/{rpc}" for rpc in re.findall(r"\brpc\s+(\w+)\s*\(", body)]
    return methods


def rpc_handlers(files: dict[str, str], methods: list[str]) -> list[Rpc]:
    """The function that handles each gRPC method: Go methods taking a *pb. request, and the
    handler object passed to addService in JavaScript."""
    by_name: dict[str, list[str]] = {}
    for method in methods:
        by_name.setdefault(method.split("/")[1].lower(), []).append(method)
    found: set[Rpc] = set()
    for file, source in files.items():
        lang = language(file)
        if lang == "go":
            root = SgRoot(source, lang).root()
            for node in root.find_all(kind="method_declaration"):
                params = node.field("parameters")
                name = node.field("name")
                if name is None or params is None or "*pb." not in params.text():
                    continue
                for method in by_name.get(name.text().lower(), []):
                    if method.endswith("/" + name.text()):  # exported, exact: not a client call
                        found.add(Rpc(method, file, _line(node)))
        elif lang in ("javascript", "typescript"):
            root = SgRoot(source, lang).root()
            functions = {s.name: s.line for s in symbols(file, source, lang)}
            for match in root.find_all(pattern="$S.addService($DEF, $IMPL)"):
                service = re.search(r"(\w+)\.service$", match.get_match("DEF").text())
                impl = match.get_match("IMPL")
                if service is None or impl.kind() != "object":
                    continue
                for pair in impl.find_all(kind="pair"):
                    key, value = pair.field("key"), pair.field("value")
                    wanted = f"{service.group(1)}/{key.text()}".lower() if key else ""
                    method = next((m for m in methods if m.lower() == wanted), None)
                    if method and value is not None and value.text() in functions:
                        found.add(Rpc(method, file, functions[value.text()]))
    return sorted(found, key=lambda r: (r.method, r.file))
