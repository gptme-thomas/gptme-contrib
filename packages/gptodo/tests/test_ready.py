"""Tests for the gptodo ready/next workable-state filters.

Regression tests for the bug where `todo` tasks were invisible to
`gptodo ready` / `gptodo next` (filters only included backlog+active),
which silently hid queued work from autonomous runners.
"""

import json
from pathlib import Path

import frontmatter
from click.testing import CliRunner

from gptodo.cli import cli, WORKABLE_STATES


def create_task(
    tasks_dir: Path,
    name: str,
    state: str,
    priority: str = "medium",
    depends: list | None = None,
):
    """Helper to create a task markdown file with frontmatter."""
    meta = {"state": state, "priority": priority, "created": "2026-01-01"}
    if depends:
        meta["depends"] = depends
    post = frontmatter.Post("Task body content.", **meta)
    task_file = tasks_dir / f"{name}.md"
    task_file.write_text(frontmatter.dumps(post))
    return task_file


def make_tasks_dir(tmp_path, monkeypatch) -> Path:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    monkeypatch.setenv("GPTODO_TASKS_DIR", str(tasks_dir))
    return tasks_dir


def ready_ids(runner_result) -> set:
    data = json.loads(runner_result.output)
    return {t["id"] for t in data["ready_tasks"]}


class TestReadyWorkableStates:
    def test_workable_states_include_todo(self):
        assert "todo" in WORKABLE_STATES

    def test_ready_default_includes_todo(self, tmp_path, monkeypatch):
        """Default `ready` must show backlog, todo, and active tasks."""
        tasks_dir = make_tasks_dir(tmp_path, monkeypatch)
        create_task(tasks_dir, "task-backlog", "backlog")
        create_task(tasks_dir, "task-todo", "todo")
        create_task(tasks_dir, "task-active", "active")
        create_task(tasks_dir, "task-done", "done")
        create_task(tasks_dir, "task-paused", "paused")

        result = CliRunner().invoke(cli, ["ready", "--json"])
        assert result.exit_code == 0
        assert ready_ids(result) == {"task-backlog", "task-todo", "task-active"}

    def test_ready_state_todo_filter(self, tmp_path, monkeypatch):
        """`ready --state todo` shows only todo tasks."""
        tasks_dir = make_tasks_dir(tmp_path, monkeypatch)
        create_task(tasks_dir, "task-todo", "todo")
        create_task(tasks_dir, "task-active", "active")

        result = CliRunner().invoke(cli, ["ready", "--state", "todo", "--json"])
        assert result.exit_code == 0
        assert ready_ids(result) == {"task-todo"}

    def test_ready_state_both_legacy_alias(self, tmp_path, monkeypatch):
        """Legacy `--state both` behaves like `all` (and includes todo)."""
        tasks_dir = make_tasks_dir(tmp_path, monkeypatch)
        create_task(tasks_dir, "task-backlog", "backlog")
        create_task(tasks_dir, "task-todo", "todo")
        create_task(tasks_dir, "task-active", "active")

        result = CliRunner().invoke(cli, ["ready", "--state", "both", "--json"])
        assert result.exit_code == 0
        assert ready_ids(result) == {"task-backlog", "task-todo", "task-active"}

    def test_ready_blocked_todo_excluded(self, tmp_path, monkeypatch):
        """A todo task with an unfinished dependency is not ready."""
        tasks_dir = make_tasks_dir(tmp_path, monkeypatch)
        create_task(tasks_dir, "task-dep", "active")
        create_task(tasks_dir, "task-todo", "todo", depends=["task-dep"])

        result = CliRunner().invoke(cli, ["ready", "--json"])
        assert result.exit_code == 0
        assert "task-todo" not in ready_ids(result)


class TestNextWorkableStates:
    def test_next_picks_todo_task(self, tmp_path, monkeypatch):
        """`next` must consider todo tasks as workable."""
        tasks_dir = make_tasks_dir(tmp_path, monkeypatch)
        create_task(tasks_dir, "task-todo", "todo", priority="high")
        create_task(tasks_dir, "task-active", "active", priority="low")

        result = CliRunner().invoke(cli, ["next", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["next_task"]["id"] == "task-todo"
