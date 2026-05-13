"""Unit tests for the Razor special handler in special_handlers.py."""
from __future__ import annotations
from datetime import datetime
import pytest
from repowise.core.ingestion.models import FileInfo
from repowise.core.ingestion.special_handlers import parse_special


def _make_file_info(path: str) -> FileInfo:
    return FileInfo(
        path=path,
        abs_path=f"/repo/{path}",
        language="razor",
        size_bytes=500,
        git_hash="",
        last_modified=datetime.now(),
        is_test=False,
        is_config=False,
        is_api_contract=False,
        is_entry_point=False,
    )


COUNTER_RAZOR = b"""\
@page "/counter"
@using MyApp.Services
@using MyApp.Models
@inherits ComponentBase
@inject CounterService CounterService

<h1>Counter</h1>
<p>Current count: @currentCount</p>

@code {
    private int currentCount = 0;

    [Parameter]
    public int InitialCount { get; set; }

    private void IncrementCount()
    {
        currentCount++;
    }
}
"""

INDEX_RAZOR = b"""\
@page "/"
@page "/index"

<h1>Hello, world!</h1>
"""

EMPTY_RAZOR = b"""\
<h1>Hello</h1>
<p>No directives here.</p>
"""


def test_component_symbol_extracted():
    """Counter.razor → a component class symbol named 'Counter'."""
    fi = _make_file_info("Pages/Counter.razor")
    result = parse_special(fi, COUNTER_RAZOR, "razor")
    assert result.parse_errors == []
    names = [s.name for s in result.symbols]
    assert "Counter" in names
    component = next(s for s in result.symbols if s.name == "Counter")
    assert component.kind == "class"
    assert component.visibility == "public"
    assert component.language == "razor"


def test_page_route_in_component():
    """@page directive route should be captured in the component symbol signature or docstring."""
    fi = _make_file_info("Pages/Counter.razor")
    result = parse_special(fi, COUNTER_RAZOR, "razor")
    component = next(s for s in result.symbols if s.name == "Counter")
    # Route should appear either in signature or docstring
    route_text = (component.signature or "") + (component.docstring or "")
    assert "/counter" in route_text


def test_multiple_page_routes():
    """Multiple @page directives should all appear in the component signature/docstring."""
    fi = _make_file_info("Pages/Index.razor")
    result = parse_special(fi, INDEX_RAZOR, "razor")
    component = next(s for s in result.symbols if s.name == "Index")
    route_text = (component.signature or "") + (component.docstring or "")
    assert "/" in route_text
    assert "/index" in route_text


def test_using_directive_imports():
    """@using directives should produce Import objects."""
    fi = _make_file_info("Pages/Counter.razor")
    result = parse_special(fi, COUNTER_RAZOR, "razor")
    module_paths = [imp.module_path for imp in result.imports]
    assert "MyApp.Services" in module_paths
    assert "MyApp.Models" in module_paths


def test_inherits_heritage():
    """@inherits directive should produce a HeritageRelation."""
    fi = _make_file_info("Pages/Counter.razor")
    result = parse_special(fi, COUNTER_RAZOR, "razor")
    assert len(result.heritage) >= 1
    rel = next((h for h in result.heritage if h.parent_name == "ComponentBase"), None)
    assert rel is not None
    assert rel.child_name == "Counter"
    assert rel.kind == "extends"


def test_inject_captured():
    """@inject directive should be reflected in the component (docstring or extra import)."""
    fi = _make_file_info("Pages/Counter.razor")
    result = parse_special(fi, COUNTER_RAZOR, "razor")
    component = next(s for s in result.symbols if s.name == "Counter")
    # CounterService should appear somewhere in the component representation
    component_text = (component.docstring or "") + (component.signature or "")
    assert "CounterService" in component_text


def test_code_block_method_extracted():
    """Methods inside @code { } block should be extracted as symbols."""
    fi = _make_file_info("Pages/Counter.razor")
    result = parse_special(fi, COUNTER_RAZOR, "razor")
    names = [s.name for s in result.symbols]
    assert "IncrementCount" in names
    method = next(s for s in result.symbols if s.name == "IncrementCount")
    assert method.kind in ("method", "function")


def test_code_block_parameter_property():
    """[Parameter] properties inside @code { } should be extracted as symbols."""
    fi = _make_file_info("Pages/Counter.razor")
    result = parse_special(fi, COUNTER_RAZOR, "razor")
    names = [s.name for s in result.symbols]
    assert "InitialCount" in names
    prop = next(s for s in result.symbols if s.name == "InitialCount")
    assert prop.kind == "variable"
    # C# attributes are captured with brackets
    assert any("Parameter" in dec for dec in prop.decorators)


def test_component_name_in_exports():
    """Component name should appear in the exports list."""
    fi = _make_file_info("Pages/Counter.razor")
    result = parse_special(fi, COUNTER_RAZOR, "razor")
    assert "Counter" in result.exports


def test_code_block_line_numbers_are_reasonable():
    """Methods inside @code { } should have line numbers > 1 (not at line 1)."""
    fi = _make_file_info("Pages/Counter.razor")
    result = parse_special(fi, COUNTER_RAZOR, "razor")
    method = next((s for s in result.symbols if s.name == "IncrementCount"), None)
    assert method is not None
    # The @code block is past the directives and HTML (line 11+), so symbols should be > 5
    assert method.start_line > 5


def test_empty_razor_no_crash():
    """A .razor file with no directives should return a valid ParsedFile."""
    fi = _make_file_info("Shared/Widget.razor")
    result = parse_special(fi, EMPTY_RAZOR, "razor")
    assert result.parse_errors == []
    assert any(s.name == "Widget" for s in result.symbols)
