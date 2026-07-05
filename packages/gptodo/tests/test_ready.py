"""Tests for `gptodo ready` state filtering (todo-visibility regression)."""

from pathlib import Path

import frontmatter
from click.testing import CliRunner

from gptodo.cli import cli


def create_task(
    tasks_dir: Path,
    name: str,
    state: str,
    priority: str = "medium",
    extra_meta: dict | None = None,
):
    meta: dict = {"state": state, "priority": priority, "created": "2026-07-01"}
    if extra_meta:
        meta.update(extra_meta)
    post = frontmatter.Post("Task body.", **meta)
    (tasks_dir / f"{name}.md").write_text(frontmatter.dumps(post))


def _ready(tmp_path: Path, *args: str):
    tasks_dir = tmp_path / "tasks"
    runner = CliRunner()
    return runner.invoke(
        cli,
        ["ready", "--jsonl", *args],
        env={"GPTODO_TASKS_DIR": str(tasks_dir)},
    )


def _make_standard_tasks(tmp_path: Path) -> Path:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    create_task(tasks_dir, "task-todo", "todo")
    create_task(tasks_dir, "task-active", "active")
    create_task(tasks_dir, "task-backlog", "backlog")
    create_task(tasks_dir, "task-done", "done")
    create_task(tasks_dir, "task-paused", "paused")
    create_task(tasks_dir, "task-someday", "someday")
    return tasks_dir


def test_ready_default_includes_todo_backlog_active(tmp_path: Path):
    # Regression (2026-07-05): `todo` tasks were invisible to `ready`, so
    # autonomous runners never picked them up.
    _make_standard_tasks(tmp_path)
    result = _ready(tmp_path)
    assert result.exit_code == 0, result.output
    assert "task-todo" in result.output
    assert "task-active" in result.output
    assert "task-backlog" in result.output
    assert "task-done" not in result.output
    assert "task-paused" not in result.output
    assert "task-someday" not in result.output


def test_ready_state_todo_filters_to_todo_only(tmp_path: Path):
    _make_standard_tasks(tmp_path)
    result = _ready(tmp_path, "--state", "todo")
    assert result.exit_code == 0, result.output
    assert "task-todo" in result.output
    assert "task-active" not in result.output
    assert "task-backlog" not in result.output


def test_ready_blocked_todo_task_is_excluded(tmp_path: Path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    create_task(tasks_dir, "task-open-dep", "active")
    create_task(
        tasks_dir,
        "task-todo-blocked",
        "todo",
        extra_meta={"depends": ["task-open-dep"]},
    )
    result = _ready(tmp_path)
    assert result.exit_code == 0, result.output
    assert "task-open-dep" in result.output
    assert "task-todo-blocked" not in result.output
