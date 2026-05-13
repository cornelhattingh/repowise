"""Tests for Phase 1: Razor language registration and traverser detection."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import pytest
from repowise.core.ingestion.models import EXTENSION_TO_LANGUAGE
from repowise.core.ingestion.traverser import FileTraverser


def test_razor_language_registered():
    """The .razor extension must map to the 'razor' language tag."""
    assert EXTENSION_TO_LANGUAGE.get(".razor") == "razor"


def test_razor_traverser_includes(tmp_path: Path):
    """FileTraverser must yield .razor files as language='razor'."""
    razor_file = tmp_path / "Counter.razor"
    razor_file.write_text("@page \"/counter\"\n<h1>Counter</h1>", encoding="utf-8")
    
    traverser = FileTraverser(tmp_path)
    files = list(traverser.traverse())
    razor_files = [f for f in files if f.path == "Counter.razor"]
    
    assert len(razor_files) == 1
    assert razor_files[0].language == "razor"
