"""Tests for task-file frontmatter validation (gptodo.utils.validate_task_file)."""

from pathlib import Path

import frontmatter

from gptodo.utils import validate_task_file


def _make_post(metadata: dict) -> "frontmatter.Post":
    post = frontmatter.Post("# Task body")
    post.metadata = {"state": "todo", "created": "2026-06-26", **metadata}
    return post


def test_autonomy_allowed_is_valid():
    post = _make_post({"autonomy": "allowed"})
    assert validate_task_file(Path("t.md"), post) == []


def test_autonomy_interactive_only_is_valid():
    post = _make_post({"autonomy": "interactive_only"})
    assert validate_task_file(Path("t.md"), post) == []


def test_autonomy_unset_is_valid():
    post = _make_post({})
    assert "autonomy" not in post.metadata
    assert validate_task_file(Path("t.md"), post) == []


def test_autonomy_invalid_value_is_flagged():
    # This is the exact typo ("autonomous") that slipped past check historically.
    post = _make_post({"autonomy": "autonomous"})
    issues = validate_task_file(Path("t.md"), post)
    assert any("Autonomy must be" in i for i in issues)
