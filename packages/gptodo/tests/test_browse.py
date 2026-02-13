"""Tests for the gptodo browse command."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import frontmatter
from click.testing import CliRunner

from gptodo.cli import cli


def create_task(tasks_dir: Path, name: str, state: str, priority: str = "medium", project: str | None = None, content: str = "Task body content."):
    """Helper to create a task markdown file with frontmatter."""
    meta = {"state": state, "priority": priority}
    if project:
        meta["project"] = project
    post = frontmatter.Post(content, **meta)
    task_file = tasks_dir / f"{name}.md"
    task_file.write_text(frontmatter.dumps(post))
    return task_file


class TestBrowseNoTasks:
    """Test browse with no tasks available."""

    def test_browse_no_tasks_dir(self, tmp_path, monkeypatch):
        """Should show error when no tasks directory exists."""
        monkeypatch.setenv("GPTODO_TASKS_DIR", str(tmp_path / "tasks"))
        runner = CliRunner()
        result = runner.invoke(cli, ["browse", "--no-fzf"])
        assert result.exit_code == 0
        assert "No tasks found" in result.output

    def test_browse_empty_tasks_dir(self, tmp_path, monkeypatch):
        """Should show error when tasks directory is empty."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        monkeypatch.setenv("GPTODO_TASKS_DIR", str(tasks_dir))
        runner = CliRunner()
        result = runner.invoke(cli, ["browse", "--no-fzf"])
        assert result.exit_code == 0
        assert "No tasks found" in result.output


class TestBrowseDefaultFilter:
    """Test that browse defaults to active+backlog tasks only."""

    def test_browse_active_only_default(self, tmp_path, monkeypatch):
        """Default browse should only show backlog and active tasks."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        create_task(tasks_dir, "task-active", "active")
        create_task(tasks_dir, "task-backlog", "backlog")
        create_task(tasks_dir, "task-done", "done")
        create_task(tasks_dir, "task-cancelled", "cancelled")
        monkeypatch.setenv("GPTODO_TASKS_DIR", str(tasks_dir))

        runner = CliRunner()
        result = runner.invoke(cli, ["browse", "--no-fzf"])
        assert "task-active" in result.output
        assert "task-backlog" in result.output
        assert "task-done" not in result.output
        assert "task-cancelled" not in result.output


class TestBrowseAllFlag:
    """Test --all flag includes done/cancelled tasks."""

    def test_browse_all_flag(self, tmp_path, monkeypatch):
        """--all should include done and cancelled tasks."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        create_task(tasks_dir, "task-active", "active")
        create_task(tasks_dir, "task-done", "done")
        create_task(tasks_dir, "task-cancelled", "cancelled")
        monkeypatch.setenv("GPTODO_TASKS_DIR", str(tasks_dir))

        runner = CliRunner()
        result = runner.invoke(cli, ["browse", "--all", "--no-fzf"])
        assert "task-active" in result.output
        assert "task-done" in result.output
        assert "task-cancelled" in result.output


class TestBrowseProjectFilter:
    """Test --project filter."""

    def test_browse_project_filter(self, tmp_path, monkeypatch):
        """--project should only show tasks from that project."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        create_task(tasks_dir, "task-gptme", "active", project="gptme")
        create_task(tasks_dir, "task-other", "active", project="other")
        create_task(tasks_dir, "task-none", "active")
        monkeypatch.setenv("GPTODO_TASKS_DIR", str(tasks_dir))

        runner = CliRunner()
        result = runner.invoke(cli, ["browse", "--project", "gptme", "--no-fzf"])
        assert "task-gptme" in result.output
        assert "task-other" not in result.output
        assert "task-none" not in result.output

    def test_browse_project_no_match(self, tmp_path, monkeypatch):
        """--project with no matches should show message."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        create_task(tasks_dir, "task-other", "active", project="other")
        monkeypatch.setenv("GPTODO_TASKS_DIR", str(tasks_dir))

        runner = CliRunner()
        result = runner.invoke(cli, ["browse", "--project", "nonexistent", "--no-fzf"])
        assert "No tasks found" in result.output or "no" in result.output.lower()


class TestBrowseStateFilter:
    """Test --state filter."""

    def test_browse_state_filter(self, tmp_path, monkeypatch):
        """--state should only show tasks with that state."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        create_task(tasks_dir, "task-active", "active")
        create_task(tasks_dir, "task-backlog", "backlog")
        create_task(tasks_dir, "task-waiting", "waiting")
        monkeypatch.setenv("GPTODO_TASKS_DIR", str(tasks_dir))

        runner = CliRunner()
        result = runner.invoke(cli, ["browse", "--state", "active", "--no-fzf"])
        assert "task-active" in result.output
        assert "task-backlog" not in result.output
        assert "task-waiting" not in result.output


class TestBrowsePagerFallback:
    """Test pager fallback when fzf is unavailable."""

    def test_browse_fzf_unavailable_falls_back_to_pager(self, tmp_path, monkeypatch):
        """When fzf is not installed, should use pager output."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        create_task(tasks_dir, "my-task", "active", content="This is task content.")
        monkeypatch.setenv("GPTODO_TASKS_DIR", str(tasks_dir))

        with patch("shutil.which", return_value=None):
            runner = CliRunner()
            result = runner.invoke(cli, ["browse"])
            # Should not crash, should show content
            assert result.exit_code == 0
            assert "my-task" in result.output

    def test_browse_no_fzf_flag_forces_pager(self, tmp_path, monkeypatch):
        """--no-fzf should use pager even when fzf is available."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        create_task(tasks_dir, "my-task", "active", content="Pager content here.")
        monkeypatch.setenv("GPTODO_TASKS_DIR", str(tasks_dir))

        with patch("shutil.which", return_value="/usr/bin/fzf"):
            runner = CliRunner()
            result = runner.invoke(cli, ["browse", "--no-fzf"])
            assert result.exit_code == 0
            assert "my-task" in result.output


class TestBrowsePagerContentFormat:
    """Test that pager output has proper formatting."""

    def test_browse_pager_content_format(self, tmp_path, monkeypatch):
        """Pager output should contain task name, state, and content with separators."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        create_task(tasks_dir, "alpha-task", "active", content="Alpha body text.")
        create_task(tasks_dir, "beta-task", "backlog", content="Beta body text.")
        monkeypatch.setenv("GPTODO_TASKS_DIR", str(tasks_dir))

        runner = CliRunner()
        result = runner.invoke(cli, ["browse", "--no-fzf"])
        output = result.output

        # Should contain both task names
        assert "alpha-task" in output
        assert "beta-task" in output
        # Should contain task content bodies
        assert "Alpha body text." in output
        assert "Beta body text." in output
        # Should contain separators (visual dividers between tasks)
        assert "═" in output or "---" in output or "===" in output


class TestBrowseFzfMode:
    """Test fzf interactive mode."""

    def test_browse_fzf_available(self, tmp_path, monkeypatch):
        """When fzf is available, should invoke subprocess with fzf."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        create_task(tasks_dir, "my-task", "active")
        monkeypatch.setenv("GPTODO_TASKS_DIR", str(tasks_dir))

        mock_result = MagicMock()
        mock_result.returncode = 130  # User cancelled with Esc
        mock_result.stdout = ""

        original_run = subprocess.run

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and cmd and cmd[0] == "fzf":
                return mock_result
            return original_run(*args, **kwargs)

        with patch("shutil.which", return_value="/usr/bin/fzf"), \
             patch("subprocess.run", side_effect=side_effect) as mock_run:
            runner = CliRunner()
            result = runner.invoke(cli, ["browse"])
            assert result.exit_code == 0
            # Verify fzf was called
            fzf_calls = [c for c in mock_run.call_args_list
                         if isinstance(c[0][0], list) and c[0][0][0] == "fzf"]
            assert len(fzf_calls) == 1

    def test_browse_fzf_preview_command(self, tmp_path, monkeypatch):
        """fzf should be called with --preview containing gptodo show."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        create_task(tasks_dir, "my-task", "active")
        monkeypatch.setenv("GPTODO_TASKS_DIR", str(tasks_dir))

        mock_result = MagicMock()
        mock_result.returncode = 130
        mock_result.stdout = ""

        original_run = subprocess.run

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and cmd and cmd[0] == "fzf":
                return mock_result
            return original_run(*args, **kwargs)

        with patch("shutil.which", return_value="/usr/bin/fzf"), \
             patch("subprocess.run", side_effect=side_effect) as mock_run:
            runner = CliRunner()
            runner.invoke(cli, ["browse"])
            fzf_calls = [c for c in mock_run.call_args_list
                         if isinstance(c[0][0], list) and c[0][0][0] == "fzf"]
            assert len(fzf_calls) == 1
            cmd_str = " ".join(fzf_calls[0][0][0])
            assert "--preview" in cmd_str
            assert "gptodo" in cmd_str and "show" in cmd_str

    def test_browse_fzf_selection_prints_task_id(self, tmp_path, monkeypatch):
        """When user selects a task in fzf, should print the task ID."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        create_task(tasks_dir, "selected-task", "active")
        monkeypatch.setenv("GPTODO_TASKS_DIR", str(tasks_dir))

        mock_fzf_result = MagicMock()
        mock_fzf_result.returncode = 0
        mock_fzf_result.stdout = "selected-task [active]"

        original_run = subprocess.run

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and cmd and cmd[0] == "fzf":
                return mock_fzf_result
            return original_run(*args, **kwargs)

        with patch("shutil.which", return_value="/usr/bin/fzf"), \
             patch("subprocess.run", side_effect=side_effect):
            runner = CliRunner()
            result = runner.invoke(cli, ["browse"])
            assert "selected-task" in result.output
