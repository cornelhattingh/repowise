"""Special handlers for non-tree-sitter file formats.

These parsers use plain text/regex/YAML parsing rather than tree-sitter because
the formats are simple enough (Dockerfile, Makefile) or require domain-specific
libraries (OpenAPI via PyYAML).

Each handler produces a fully-populated ParsedFile — the same output model as
the tree-sitter parsers — so the rest of the pipeline treats them identically.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import structlog

from .models import CallSite, FileInfo, HeritageRelation, Import, ParsedFile, Symbol

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def parse_special(file_info: FileInfo, source: bytes, lang: str) -> ParsedFile:
    """Route to the correct special handler based on language tag."""
    handler: Callable[[FileInfo, bytes], ParsedFile] = {
        "openapi": _parse_openapi,
        "dockerfile": _parse_dockerfile,
        "makefile": _parse_makefile,
        "razor": _parse_razor,
    }.get(lang, _parse_unknown)
    try:
        return handler(file_info, source)
    except Exception as exc:
        log.warning("Special handler failed", path=file_info.path, error=str(exc))
        return _empty(file_info, parse_errors=[str(exc)])


# ---------------------------------------------------------------------------
# OpenAPI handler
# ---------------------------------------------------------------------------


def _parse_openapi(file_info: FileInfo, source: bytes) -> ParsedFile:
    """Parse OpenAPI 2 / 3 YAML or JSON specs."""
    try:
        import yaml  # pyyaml, already in dependencies
    except ImportError:
        return _empty(file_info, parse_errors=["pyyaml not installed"])

    try:
        data = yaml.safe_load(source.decode("utf-8", errors="replace"))
    except Exception as exc:
        return _empty(file_info, parse_errors=[f"YAML parse error: {exc}"])

    if not isinstance(data, dict):
        return _empty(file_info, parse_errors=["Not a YAML mapping"])

    # Confirm it's an OpenAPI/Swagger spec
    if "openapi" not in data and "swagger" not in data:
        return _empty(file_info, parse_errors=["Not an OpenAPI/Swagger spec"])

    symbols: list[Symbol] = []
    _title = (data.get("info") or {}).get("title", file_info.path)

    paths = data.get("paths") or {}
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, spec in methods.items():
            if method.lower() in ("get", "post", "put", "patch", "delete", "head", "options"):
                op_id = (spec or {}).get("operationId", f"{method.upper()} {path}")
                summary = (spec or {}).get("summary")
                symbols.append(
                    Symbol(
                        id=f"{file_info.path}::{op_id}",
                        name=op_id,
                        qualified_name=op_id,
                        kind="function",
                        signature=f"{method.upper()} {path}",
                        start_line=1,
                        end_line=1,
                        docstring=summary,
                        visibility="public",
                        language="openapi",
                    )
                )

    # Components / schemas as type symbols
    components = (data.get("components") or {}).get("schemas") or (data.get("definitions") or {})
    for schema_name in components:
        symbols.append(
            Symbol(
                id=f"{file_info.path}::{schema_name}",
                name=schema_name,
                qualified_name=schema_name,
                kind="type_alias",
                signature=f"schema {schema_name}",
                start_line=1,
                end_line=1,
                docstring=None,
                visibility="public",
                language="openapi",
            )
        )

    return ParsedFile(
        file_info=file_info,
        symbols=symbols,
        imports=[],
        exports=[s.name for s in symbols],
        docstring=str(data.get("info", {}).get("description", "")) or None,
        parse_errors=[],
    )


# ---------------------------------------------------------------------------
# Dockerfile handler
# ---------------------------------------------------------------------------

_FROM_RE = re.compile(r"^\s*FROM\s+([^\s]+)", re.IGNORECASE)
_COPY_RE = re.compile(r"^\s*COPY\s+", re.IGNORECASE)
_RUN_RE = re.compile(r"^\s*RUN\s+", re.IGNORECASE)
_ENTRYPOINT_RE = re.compile(r"^\s*(?:ENTRYPOINT|CMD)\s+(.+)", re.IGNORECASE)
_EXPOSE_RE = re.compile(r"^\s*EXPOSE\s+(\d+)", re.IGNORECASE)
_ENV_RE = re.compile(r"^\s*ENV\s+(\w+)", re.IGNORECASE)
_ARG_RE = re.compile(r"^\s*ARG\s+(\w+)", re.IGNORECASE)


def _parse_dockerfile(file_info: FileInfo, source: bytes) -> ParsedFile:
    text = source.decode("utf-8", errors="replace")
    lines = text.splitlines()
    imports: list[Import] = []
    symbols: list[Symbol] = []

    for lineno, line in enumerate(lines, start=1):
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue

        # FROM → import
        m = _FROM_RE.match(line)
        if m:
            image = m.group(1)
            imports.append(
                Import(
                    raw_statement=line.strip(),
                    module_path=image,
                    imported_names=[image],
                    is_relative=False,
                    resolved_file=None,
                )
            )
            continue

        # ENTRYPOINT / CMD → entry-point symbol
        m = _ENTRYPOINT_RE.match(line)
        if m:
            name = "entrypoint" if "ENTRYPOINT" in line.upper() else "cmd"
            symbols.append(
                Symbol(
                    id=f"{file_info.path}::{name}",
                    name=name,
                    qualified_name=name,
                    kind="function",
                    signature=line.strip(),
                    start_line=lineno,
                    end_line=lineno,
                    docstring=None,
                    visibility="public",
                    language="dockerfile",
                )
            )
            continue

        # EXPOSE → constant
        m = _EXPOSE_RE.match(line)
        if m:
            port = m.group(1)
            symbols.append(
                Symbol(
                    id=f"{file_info.path}::EXPOSE_{port}",
                    name=f"EXPOSE_{port}",
                    qualified_name=f"port_{port}",
                    kind="constant",
                    signature=line.strip(),
                    start_line=lineno,
                    end_line=lineno,
                    docstring=None,
                    visibility="public",
                    language="dockerfile",
                )
            )

    return ParsedFile(
        file_info=file_info,
        symbols=symbols,
        imports=imports,
        exports=[],
        docstring=None,
        parse_errors=[],
    )


# ---------------------------------------------------------------------------
# Makefile handler
# ---------------------------------------------------------------------------

# Matches: target_name: [prerequisites...]
_TARGET_RE = re.compile(r"^([a-zA-Z0-9_][a-zA-Z0-9_\-./]*):[^=]")
_INCLUDE_RE = re.compile(r"^include\s+(.+)", re.IGNORECASE)
_PHONY_RE = re.compile(r"^\.PHONY\s*:\s*(.+)")


# ---------------------------------------------------------------------------
# Razor (Blazor) handler — regex patterns
# ---------------------------------------------------------------------------
_RAZOR_PAGE_RE = re.compile(r'@page\s+"([^"]+)"')
_RAZOR_USING_RE = re.compile(r'^@using\s+(\S+)', re.MULTILINE)
_RAZOR_INHERITS_RE = re.compile(r'^@inherits\s+(\S+)', re.MULTILINE)
_RAZOR_INJECT_RE = re.compile(r'^@inject\s+(\S+)\s+(\S+)', re.MULTILINE)
_RAZOR_CODE_OPEN_RE = re.compile(r'@code\s*\{')


def _parse_makefile(file_info: FileInfo, source: bytes) -> ParsedFile:
    text = source.decode("utf-8", errors="replace")
    lines = text.splitlines()
    symbols: list[Symbol] = []
    imports: list[Import] = []
    phony_targets: set[str] = set()

    # First pass: collect .PHONY targets
    for line in lines:
        m = _PHONY_RE.match(line)
        if m:
            phony_targets.update(m.group(1).split())

    # Second pass: extract targets
    for lineno, line in enumerate(lines, start=1):
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue

        m = _TARGET_RE.match(line)
        if m:
            target = m.group(1)
            if not target.startswith("."):  # skip .PHONY, .SUFFIXES, etc.
                symbols.append(
                    Symbol(
                        id=f"{file_info.path}::{target}",
                        name=target,
                        qualified_name=target,
                        kind="function",
                        signature=f"{target}:",
                        start_line=lineno,
                        end_line=lineno,
                        docstring=None,
                        visibility="public",
                        language="makefile",
                    )
                )
            continue

        m = _INCLUDE_RE.match(line)
        if m:
            include_path = m.group(1).strip()
            imports.append(
                Import(
                    raw_statement=line.strip(),
                    module_path=include_path,
                    imported_names=[],
                    is_relative=True,
                    resolved_file=None,
                )
            )

    return ParsedFile(
        file_info=file_info,
        symbols=symbols,
        imports=imports,
        exports=[s.name for s in symbols],
        docstring=None,
        parse_errors=[],
    )


# ---------------------------------------------------------------------------
# Razor (Blazor) handler
# ---------------------------------------------------------------------------


def _extract_razor_code_block(text: str) -> tuple[str, int] | None:
    """Extract the content of the @code { } block and its 1-based start line.

    Returns (code_body, start_line) or None if no @code block found.
    The start_line is the line where @code { appears.
    """
    m = _RAZOR_CODE_OPEN_RE.search(text)
    if not m:
        return None

    brace_start = m.end() - 1  # position of the opening {
    depth = 0
    i = brace_start
    while i < len(text):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                code_body = text[brace_start + 1:i]
                start_line = text[:m.start()].count('\n') + 1
                return code_body, start_line
        i += 1
    return None  # unclosed brace


def _parse_code_block_csharp(
    code_body: str,
    file_info: FileInfo,
    component_name: str,
    code_start_line: int,
) -> tuple[list[Symbol], list[CallSite], list[str]]:
    """Parse the @code block content as C# and return symbols, calls, and parse errors.

    Uses a lazy import of ASTParser to avoid circular imports.
    """
    # Lazy import to avoid circular dependency: parser.py → special_handlers.py
    from .parser import ASTParser  # noqa: PLC0415

    # Wrap in a class so the C# parser sees valid syntax
    wrapped = f"class __RazorCodeBlock {{\n{code_body}\n}}"
    # Line offset: The wrapper adds 1 line before the body.
    # In the parsed result: line 1 = wrapper, line 2+ = body.
    # Original file: code_start_line = @code { line, body starts at code_start_line + 1.
    # So: parsed line 2 → original line code_start_line + 1.
    # Therefore: original_line = parsed_line - 1 + code_start_line.
    line_offset = code_start_line - 1

    synthetic_fi = FileInfo(
        path=file_info.path,
        abs_path=file_info.abs_path,
        language="csharp",  # type: ignore[arg-type]
        size_bytes=len(wrapped),
        git_hash="",
        last_modified=file_info.last_modified,
        is_test=file_info.is_test,
        is_config=False,
        is_api_contract=False,
        is_entry_point=False,
    )

    parser = ASTParser()
    parsed = parser.parse_file(synthetic_fi, wrapped.encode("utf-8"))

    symbols: list[Symbol] = []
    # Build a mapping from old symbol IDs to new symbol IDs for callsite remapping
    sym_id_map: dict[str, str] = {}
    
    for sym in parsed.symbols:
        # Skip the __RazorCodeBlock wrapper class itself
        if sym.name == "__RazorCodeBlock":
            continue
        
        new_sym_id = f"{file_info.path}::{component_name}::{sym.name}"
        # Record the mapping from the synthetic ID to the adjusted ID
        sym_id_map[sym.id] = new_sym_id
        
        adjusted = Symbol(
            id=new_sym_id,
            name=sym.name,
            qualified_name=f"{component_name}.{sym.name}",
            kind=sym.kind,
            signature=sym.signature,
            start_line=sym.start_line + line_offset,
            end_line=sym.end_line + line_offset,
            docstring=sym.docstring,
            decorators=sym.decorators,
            visibility=sym.visibility,
            is_async=sym.is_async,
            language="razor",
            parent_name=component_name,
        )
        symbols.append(adjusted)

    # Adjust call line numbers and remap caller_symbol_id
    calls = []
    for c in parsed.calls:
        # Remap the caller_symbol_id from synthetic to adjusted
        adjusted_caller_id = sym_id_map.get(c.caller_symbol_id, c.caller_symbol_id)
        calls.append(CallSite(
            target_name=c.target_name,
            receiver_name=c.receiver_name,
            caller_symbol_id=adjusted_caller_id,
            line=c.line + line_offset,
            argument_count=c.argument_count,
        ))

    return symbols, calls, parsed.parse_errors


def _parse_razor(file_info: FileInfo, source: bytes) -> ParsedFile:
    """Parse a Blazor Razor component file (.razor).

    Extracts:
    - Component class symbol from the filename stem
    - @page routes → captured in component signature / docstring
    - @using directives → Import objects
    - @inherits → HeritageRelation
    - @inject dependencies → captured in component docstring
    - @code { } block → parsed as C# for methods/properties/etc.
    """
    from pathlib import Path as _Path

    text = source.decode("utf-8", errors="replace")
    component_name = _Path(file_info.path).stem

    # --- Directives ---
    page_routes = _RAZOR_PAGE_RE.findall(text)
    imports: list[Import] = []
    heritage: list[HeritageRelation] = []

    for m in _RAZOR_USING_RE.finditer(text):
        ns = m.group(1)
        imports.append(
            Import(
                raw_statement=m.group(0),
                module_path=ns,
                imported_names=["*"],
                is_relative=False,
                resolved_file=None,
            )
        )

    for m in _RAZOR_INHERITS_RE.finditer(text):
        base = m.group(1).split("<")[0]  # strip generic params if present
        inherits_line = text[: m.start()].count("\n") + 1
        heritage.append(
            HeritageRelation(
                child_name=component_name,
                parent_name=base,
                kind="extends",
                line=inherits_line,
            )
        )

    inject_pairs: list[tuple[str, str]] = []
    for m in _RAZOR_INJECT_RE.finditer(text):
        inject_pairs.append((m.group(1), m.group(2)))

    # --- Component symbol ---
    route_part = " ".join(f'@page "{r}"' for r in page_routes) if page_routes else ""
    inject_part = (
        "; ".join(f"@inject {svc} {prop}" for svc, prop in inject_pairs)
        if inject_pairs
        else ""
    )
    doc_parts = []
    if route_part:
        doc_parts.append(f"Routes: {route_part}")
    if inject_part:
        doc_parts.append(f"Injects: {inject_part}")
    component_doc = "\n".join(doc_parts) or None

    component_sig = f"@component {component_name}"
    if route_part:
        component_sig = f"{component_sig} {route_part}"

    component_symbol = Symbol(
        id=f"{file_info.path}::{component_name}",
        name=component_name,
        qualified_name=component_name,
        kind="class",
        signature=component_sig,
        start_line=1,
        end_line=text.count("\n") + 1,
        docstring=component_doc,
        visibility="public",
        language="razor",
    )

    # --- @code block ---
    code_symbols: list[Symbol] = []
    code_calls = []
    code_parse_errors: list[str] = []
    code_result = _extract_razor_code_block(text)
    if code_result:
        code_body, code_start_line = code_result
        try:
            code_symbols, code_calls, code_parse_errors = _parse_code_block_csharp(
                code_body, file_info, component_name, code_start_line
            )
        except Exception as exc:
            log.warning("Razor @code block parse failed", path=file_info.path, error=str(exc))
            code_parse_errors = [str(exc)]

    return ParsedFile(
        file_info=file_info,
        symbols=[component_symbol] + code_symbols,
        imports=imports,
        exports=[component_name],
        calls=code_calls,
        heritage=heritage,
        docstring=component_doc,
        parse_errors=code_parse_errors,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_unknown(file_info: FileInfo, source: bytes) -> ParsedFile:
    return _empty(file_info, parse_errors=[f"No special handler for {file_info.language}"])


def _empty(file_info: FileInfo, parse_errors: list[str] | None = None) -> ParsedFile:
    return ParsedFile(
        file_info=file_info,
        symbols=[],
        imports=[],
        exports=[],
        docstring=None,
        parse_errors=parse_errors or [],
    )
