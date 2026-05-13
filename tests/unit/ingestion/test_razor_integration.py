"""Integration tests for Blazor Razor file ingestion via FileTraverser + ASTParser."""
from __future__ import annotations

from pathlib import Path

import pytest

from repowise.core.ingestion.models import FileInfo
from repowise.core.ingestion.traverser import FileTraverser
from repowise.core.ingestion.parser import ASTParser

# Path to the Blazor fixture relative to the repo root
BLAZOR_FIXTURE = Path(__file__).parent.parent.parent / "fixtures" / "blazor_app"


@pytest.fixture(scope="module")
def blazor_files() -> list[FileInfo]:
    """Traverse the blazor_app fixture and return all file infos."""
    traverser = FileTraverser(BLAZOR_FIXTURE)
    return list(traverser.traverse())


@pytest.fixture(scope="module")
def razor_files(blazor_files: list[FileInfo]) -> list[FileInfo]:
    """Filter to only .razor files."""
    return [f for f in blazor_files if f.language == "razor"]


@pytest.fixture(scope="module")
def csharp_files(blazor_files: list[FileInfo]) -> list[FileInfo]:
    """Filter to only .cs files."""
    return [f for f in blazor_files if f.language == "csharp"]


class TestBlazorTraversal:
    def test_razor_files_are_included(self, razor_files: list[FileInfo]) -> None:
        """All .razor files in the fixture must be traversed."""
        names = {Path(f.path).name for f in razor_files}
        assert "Counter.razor" in names
        assert "Index.razor" in names
        assert "NavMenu.razor" in names

    def test_csharp_files_are_included(self, csharp_files: list[FileInfo]) -> None:
        """C# service/model files must still be traversed."""
        names = {Path(f.path).name for f in csharp_files}
        assert "CounterService.cs" in names
        assert "CounterModel.cs" in names

    def test_razor_language_tag(self, razor_files: list[FileInfo]) -> None:
        """All traversed .razor files have language='razor'."""
        for f in razor_files:
            assert f.language == "razor", f"{f.path} should be 'razor'"


class TestBlazorParsing:
    @pytest.fixture(scope="class")
    def parsed_counter(self, blazor_files: list[FileInfo]) -> object:
        """Parse Counter.razor and return the ParsedFile."""
        fi = next(f for f in blazor_files if Path(f.path).name == "Counter.razor")
        content = Path(fi.abs_path).read_bytes()
        parser = ASTParser()
        return parser.parse_file(fi, content)

    @pytest.fixture(scope="class")
    def parsed_navmenu(self, blazor_files: list[FileInfo]) -> object:
        """Parse NavMenu.razor and return the ParsedFile."""
        fi = next(f for f in blazor_files if Path(f.path).name == "NavMenu.razor")
        content = Path(fi.abs_path).read_bytes()
        parser = ASTParser()
        return parser.parse_file(fi, content)

    def test_counter_component_symbol(self, parsed_counter) -> None:
        """Counter.razor must have a component class symbol named 'Counter'."""
        assert parsed_counter.parse_errors == []
        names = [s.name for s in parsed_counter.symbols]
        assert "Counter" in names
        component = next(s for s in parsed_counter.symbols if s.name == "Counter")
        assert component.kind == "class"
        assert component.language == "razor"

    def test_counter_route_captured(self, parsed_counter) -> None:
        """The @page '/counter' route should be in the component representation."""
        component = next(s for s in parsed_counter.symbols if s.name == "Counter")
        route_text = (component.signature or "") + (component.docstring or "")
        assert "/counter" in route_text

    def test_counter_using_imports(self, parsed_counter) -> None:
        """@using BlazorApp.Services must produce an Import."""
        module_paths = [i.module_path for i in parsed_counter.imports]
        assert "BlazorApp.Services" in module_paths

    def test_counter_code_block_symbols(self, parsed_counter) -> None:
        """Methods inside @code { } must be extracted as symbols."""
        names = [s.name for s in parsed_counter.symbols]
        assert "IncrementCount" in names
        assert "OnInitialized" in names

    def test_counter_parameter_property(self, parsed_counter) -> None:
        """[Parameter] properties must be extracted and tagged."""
        names = [s.name for s in parsed_counter.symbols]
        assert "InitialCount" in names
        prop = next(s for s in parsed_counter.symbols if s.name == "InitialCount")
        assert "[Parameter]" in prop.decorators

    def test_counter_exports_component_name(self, parsed_counter) -> None:
        """Counter should be in the exports list."""
        assert "Counter" in parsed_counter.exports

    def test_navmenu_inherits_heritage(self, parsed_navmenu) -> None:
        """NavMenu.razor @inherits LayoutComponentBase → HeritageRelation."""
        heritage = parsed_navmenu.heritage
        assert len(heritage) >= 1
        rel = next((h for h in heritage if h.parent_name == "LayoutComponentBase"), None)
        assert rel is not None
        assert rel.child_name == "NavMenu"
        assert rel.kind == "extends"
