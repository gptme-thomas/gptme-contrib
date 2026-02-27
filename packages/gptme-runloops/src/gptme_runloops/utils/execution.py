"""Execution utilities for running gptme, Claude Code, and Codex."""

import logging
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Global log directory (not in workspace to prevent Issue #151 recursive grep)
GLOBAL_LOG_DIR = Path.home() / ".cache" / "gptme" / "logs"
GLOBAL_LOG_DIR.mkdir(parents=True, exist_ok=True)


def compile_context(
    workspace: Path,
    runtime: str,
    instruction_doc: str,
) -> str:
    """Compile workspace context using the shared compile-context.sh script.

    Mirrors what run-with-claude.sh and run-with-codex.sh do before launching
    their respective backends: runs compile-context.sh to produce
    tmp/full-context.md, then returns its contents.

    Args:
        workspace: Path to workspace directory
        runtime: Runtime name (e.g. "Claude Code", "Codex")
        instruction_doc: Instruction doc filename (e.g. "CLAUDE.md", "AGENTS.md")

    Returns:
        Compiled context string, or empty string if compilation fails
    """
    compile_script = workspace / "scripts" / "shared" / "compile-context.sh"
    if not compile_script.exists():
        logger.warning(f"Context compilation script not found: {compile_script}")
        return ""

    try:
        result = subprocess.run(
            [
                str(compile_script),
                "--runtime",
                runtime,
                "--instruction-doc",
                instruction_doc,
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning(
                f"Context compilation failed (exit {result.returncode}): {result.stderr}"
            )
            return ""

        context_file = workspace / "tmp" / "full-context.md"
        if context_file.exists():
            return context_file.read_text()

        logger.warning("Context compiled but tmp/full-context.md not found")
        return ""

    except subprocess.TimeoutExpired:
        logger.warning("Context compilation timed out")
        return ""
    except Exception as e:
        logger.warning(f"Context compilation error: {e}")
        return ""


class ExecutionResult:
    """Result from gptme execution."""

    def __init__(self, exit_code: int, timed_out: bool = False):
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.success = exit_code == 0


def execute_gptme(
    prompt: str,
    workspace: Path,
    timeout: int,
    non_interactive: bool = True,
    shell_timeout: int = 120,
    env: Optional[dict] = None,
    run_type: str = "run",
    tools: Optional[str] = None,
) -> ExecutionResult:
    """Execute gptme with the given prompt.

    Args:
        prompt: Prompt text to pass to gptme
        workspace: Working directory for execution
        timeout: Maximum execution time in seconds
        non_interactive: Run in non-interactive mode
        shell_timeout: Shell command timeout in seconds
        env: Additional environment variables
        run_type: Type of run (for log file naming)
        tools: Tool allowlist string (e.g. "gptodo,save,append")

    Returns:
        ExecutionResult with exit code and status
    """
    # Create global log file for this run
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = GLOBAL_LOG_DIR / f"{run_type}-{timestamp}.log"
    # Create temporary prompt file
    prompt_file = workspace / f".gptme-prompt-{os.getpid()}.txt"
    prompt_file.write_text(prompt)

    try:
        # Build gptme command
        # Find gptme in PATH (typically pipx-managed)
        gptme_path = shutil.which("gptme")
        if not gptme_path:
            raise RuntimeError(
                "gptme not found in PATH. Install with: pipx install gptme"
            )
        cmd = [gptme_path]
        if non_interactive:
            cmd.append("--non-interactive")

        if tools:
            cmd.extend(["--tools", tools])

        # this line is essential for the prompt file path to not be mistaken for a command
        cmd.append("'Here is the prompt to follow:'")

        # mentioning the file here includes its contents in the initial message
        cmd.append(str(prompt_file))

        # Set up environment
        run_env = os.environ.copy()
        run_env["GPTME_SHELL_TIMEOUT"] = str(shell_timeout)
        run_env["GPTME_CHAT_HISTORY"] = "true"

        if env:
            run_env.update(env)

        # Use tee to stream output to both terminal and log file
        # This gives us real-time journald logging AND complete log file
        # Use shlex.join for proper escaping to prevent command injection
        cmd_with_tee = f"{shlex.join(cmd)} 2>&1 | tee {shlex.quote(str(log_file))}"

        # Write header to log file first
        with log_file.open("w") as f:
            f.write(f"=== {run_type} run at {timestamp} ===\n")
            f.write(f"Working directory: {workspace}\n")
            f.write(f"Command: {' '.join(cmd)}\n")
            f.write(f"Timeout: {timeout}s\n")
            f.write(f"Shell timeout: {shell_timeout}s\n\n")
            f.write("=== Output ===\n")

        # Execute with tee - streams to both stdout and log file
        try:
            result = subprocess.run(
                cmd_with_tee,
                shell=True,  # Required for pipe
                cwd=workspace,
                env=run_env,
                timeout=timeout,
            )

            # Append exit code
            with log_file.open("a") as f:
                f.write("\n=== Execution completed ===\n")
                f.write(f"Exit code: {result.returncode}\n")

            return ExecutionResult(exit_code=result.returncode)

        except subprocess.TimeoutExpired:
            # Log timeout to file (append to preserve tee output)
            with log_file.open("a") as f:
                f.write("\n=== Execution timed out ===\n")
                f.write(f"Status: TIMED OUT after {timeout}s\n")

            print(f"ERROR: Execution timed out after {timeout}s", file=sys.stderr)
            return ExecutionResult(exit_code=124, timed_out=True)

    finally:
        # Clean up prompt file
        if prompt_file.exists():
            prompt_file.unlink()


def execute_claude_code(
    prompt: str,
    workspace: Path,
    timeout: int,
    env: Optional[dict] = None,
    run_type: str = "run",
) -> ExecutionResult:
    """Execute Claude Code with the given prompt.

    Compiles workspace context (static + dynamic) and passes it via
    --append-system-prompt, mirroring run-with-claude.sh. The prompt
    itself is piped via stdin.

    Args:
        prompt: Prompt text to pass via stdin
        workspace: Working directory for execution
        timeout: Maximum execution time in seconds
        env: Additional environment variables
        run_type: Type of run (for log file naming)

    Returns:
        ExecutionResult with exit code and status
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = GLOBAL_LOG_DIR / f"{run_type}-claude-{timestamp}.log"

    claude_path = shutil.which("claude")
    if not claude_path:
        raise RuntimeError("claude not found in PATH. Install Claude Code CLI first.")

    # Compile workspace context (like run-with-claude.sh does)
    context = compile_context(workspace, "Claude Code", "CLAUDE.md")

    # Build command
    cmd = [
        claude_path,
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
    ]

    # Pass compiled context as system prompt (like run-with-claude.sh)
    if context:
        cmd.extend(["--append-system-prompt", context])

    # Read config from env (matching shell wrapper exports)
    max_budget = os.environ.get("CLAUDE_MAX_BUDGET_USD")
    if max_budget:
        cmd.extend(["--max-budget-usd", max_budget])

    max_turns = os.environ.get("CLAUDE_MAX_TURNS")
    if max_turns:
        cmd.extend(["--max-turns", max_turns])

    model = os.environ.get("CLAUDE_MODEL")
    if model:
        cmd.extend(["--model", model])

    # Set up environment
    run_env = os.environ.copy()
    # Ensure Claude's Bash tool gets PATH entries from bashrc
    run_env["BASH_ENV"] = str(Path.home() / ".bashrc")
    if env:
        run_env.update(env)

    # Use pipefail so tee doesn't mask non-zero exit codes
    cmd_str = shlex.join(cmd)
    cmd_with_tee = (
        f"set -o pipefail; {cmd_str} 2>&1 " f"| tee {shlex.quote(str(log_file))}"
    )

    # Write log header
    with log_file.open("w") as f:
        f.write(f"=== {run_type} claude-code run at {timestamp} ===\n")
        f.write(f"Working directory: {workspace}\n")
        f.write(f"Command: {cmd_str}\n")
        f.write(f"Context compiled: {'yes' if context else 'no'}\n")
        f.write(f"Timeout: {timeout}s\n\n")
        f.write("=== Output ===\n")

    try:
        result = subprocess.run(
            ["bash", "-c", cmd_with_tee],
            cwd=workspace,
            env=run_env,
            timeout=timeout,
            input=prompt,
            text=True,
        )

        with log_file.open("a") as f:
            f.write("\n=== Execution completed ===\n")
            f.write(f"Exit code: {result.returncode}\n")

        return ExecutionResult(exit_code=result.returncode)

    except subprocess.TimeoutExpired:
        with log_file.open("a") as f:
            f.write("\n=== Execution timed out ===\n")
            f.write(f"Status: TIMED OUT after {timeout}s\n")

        print(
            f"ERROR: Claude Code execution timed out after {timeout}s", file=sys.stderr
        )
        return ExecutionResult(exit_code=124, timed_out=True)


def execute_codex(
    prompt: str,
    workspace: Path,
    timeout: int,
    env: Optional[dict] = None,
    run_type: str = "run",
) -> ExecutionResult:
    """Execute Codex with the given prompt.

    Compiles workspace context (static + dynamic) and prepends it to
    the prompt, mirroring run-with-codex.sh. The combined text is
    piped via stdin.

    Args:
        prompt: Prompt text to pass via stdin
        workspace: Working directory for execution
        timeout: Maximum execution time in seconds
        env: Additional environment variables
        run_type: Type of run (for log file naming)

    Returns:
        ExecutionResult with exit code and status
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = GLOBAL_LOG_DIR / f"{run_type}-codex-{timestamp}.log"

    # Find codex in PATH or common install locations
    codex_path = shutil.which("codex")
    if not codex_path:
        for candidate in [
            Path.home() / ".local" / "bin" / "codex",
            Path("/usr/local/bin/codex"),
        ]:
            if candidate.exists():
                codex_path = str(candidate)
                break
    if not codex_path:
        raise RuntimeError("codex not found in PATH or common install locations.")

    # Compile workspace context (like run-with-codex.sh does)
    context = compile_context(workspace, "Codex", "AGENTS.md")

    # Prepend context to prompt (Codex has no --append-system-prompt)
    if context:
        combined_prompt = f"{context}\n---\n\n{prompt}"
    else:
        combined_prompt = prompt

    # Build command
    cmd = [codex_path, "exec", "-C", str(workspace), "--json", "-"]

    sandbox = os.environ.get("CODEX_SANDBOX")
    if sandbox:
        cmd.extend(["--sandbox", sandbox])
    else:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")

    model = os.environ.get("CODEX_MODEL")
    if model:
        cmd.extend(["--model", model])

    # Set up environment
    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    # Use pipefail so tee doesn't mask non-zero exit codes
    cmd_str = shlex.join(cmd)
    cmd_with_tee = (
        f"set -o pipefail; {cmd_str} 2>&1 " f"| tee {shlex.quote(str(log_file))}"
    )

    # Write log header
    with log_file.open("w") as f:
        f.write(f"=== {run_type} codex run at {timestamp} ===\n")
        f.write(f"Working directory: {workspace}\n")
        f.write(f"Command: {cmd_str}\n")
        f.write(f"Context compiled: {'yes' if context else 'no'}\n")
        f.write(f"Timeout: {timeout}s\n\n")
        f.write("=== Output ===\n")

    try:
        result = subprocess.run(
            ["bash", "-c", cmd_with_tee],
            cwd=workspace,
            env=run_env,
            timeout=timeout,
            input=combined_prompt,
            text=True,
        )

        with log_file.open("a") as f:
            f.write("\n=== Execution completed ===\n")
            f.write(f"Exit code: {result.returncode}\n")

        return ExecutionResult(exit_code=result.returncode)

    except subprocess.TimeoutExpired:
        with log_file.open("a") as f:
            f.write("\n=== Execution timed out ===\n")
            f.write(f"Status: TIMED OUT after {timeout}s\n")

        print(f"ERROR: Codex execution timed out after {timeout}s", file=sys.stderr)
        return ExecutionResult(exit_code=124, timed_out=True)
