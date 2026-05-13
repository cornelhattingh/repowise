## Plan Complete: Blazor Razor File Support

Added `.razor` (Blazor component) files as a first-class indexed language in RepoWise. Previously `.razor` files were completely invisible to the pipeline (extension unrecognised → skipped). The implementation extracts component class symbols, `@page` routes, `@using` imports, `@inherits` heritage, `@inject` dependencies, and full C# symbols from `@code { }` blocks. A secondary bug was fixed: the existing `openapi` / `dockerfile` / `makefile` special-handler dispatch was unreachable; restructuring the parser dispatch order fixed this for all three languages as well as enabling Razor.

**Phases Completed:** 3 of 3

1. ✅ Phase 1: Language Registration & Parser Dispatch Fix
2. ✅ Phase 2: Razor Special Handler
3. ✅ Phase 3: Fixtures & Integration Tests

---

**All Files Created/Modified:**

- `packages/core/src/repowise/core/ingestion/models.py` — added `"razor"` to `LanguageTag` Literal
- `packages/core/src/repowise/core/ingestion/languages/registry.py` — added `LanguageSpec(tag="razor", display_name="Blazor/C#", extensions={".razor"}, color_hex="#512bd4")`
- `packages/core/src/repowise/core/ingestion/parser.py` — moved special-handler dispatch before grammar/config guard; added `"razor"` to the set
- `packages/core/src/repowise/core/ingestion/special_handlers.py` — added `_parse_razor`, `_extract_razor_code_block`, `_parse_code_block_csharp`; registered `"razor"` in dispatcher
- `packages/core/src/repowise/core/ingestion/queries/csharp.scm` — added `(attribute_list)?` capture to all C# symbol patterns (both modifier-capturing and fallback variants)
- `tests/unit/ingestion/test_razor_phase1.py` — TDD tests for language registration and traverser detection
- `tests/unit/ingestion/test_razor_special_handler.py` — unit tests for the Razor special handler (11 tests)
- `tests/unit/ingestion/test_razor_integration.py` — integration tests against real fixture files (10 tests)
- `tests/fixtures/blazor_app/BlazorApp.csproj` — Blazor WebAssembly project fixture
- `tests/fixtures/blazor_app/Program.cs` — app entry point fixture
- `tests/fixtures/blazor_app/Pages/Counter.razor` — component fixture with @page, @inject, @code block, [Parameter]
- `tests/fixtures/blazor_app/Pages/Index.razor` — minimal route component fixture
- `tests/fixtures/blazor_app/Shared/NavMenu.razor` — @inherits fixture
- `tests/fixtures/blazor_app/Services/CounterService.cs` — C# service fixture
- `tests/fixtures/blazor_app/Models/CounterModel.cs` — C# record fixture

---

**Key Functions/Classes Added:**

- `_parse_razor(file_info, source)` — main Razor handler; extracts directives and code block
- `_extract_razor_code_block(text)` — brace-counting extractor for `@code { }` blocks
- `_parse_code_block_csharp(code_body, file_info, component_name, code_start_line)` — lazily imports `ASTParser` to parse the C# code block; remaps symbol IDs and line offsets; returns `(symbols, calls, parse_errors)`

---

**Test Coverage:**

- Total tests written: 23 (2 phase-1 + 11 unit + 10 integration)
- All tests passing: ✅ (452 total ingestion tests pass, 2 xfailed expected)

---

**Recommendations for Next Steps:**

- Component-to-component references (e.g. `<NavMenu />` in Razor HTML) could be extracted as `calls` edges in a future phase
- The `@code` block brace-counter doesn't handle braces inside string literals; a more robust extractor could handle edge cases in complex components
- The C# import resolver could be extended to resolve `@using` namespace references from Razor files into the same project index used for `.cs` files
