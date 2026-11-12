from crewai.tools import tool
from pathlib import Path
import shutil
import subprocess


SANDBOX_DIR = Path(__file__).parents[3] / "sandbox"
SANDBOX_DIR.mkdir(parents=True, exist_ok=True)


PROTECTED = {".venv", "pyproject.toml", "uv.lock", ".python-version"}  # the sandbox's uv project
MAX_READ_CHARS = 100_000


def _safe_path(filename: str) -> Path:
    """Map an agent-supplied filename to a file directly inside SANDBOX_DIR, or raise ValueError.

    Rejects absolute paths, '..', subdirectories and symlinks that point outside the sandbox
    (code run in Docker could create one, and these tools run on the host)."""
    name = (filename or "").strip()
    if not name or name in (".", "..") or Path(name).name != name or "\\" in name:
        raise ValueError(f"'{filename}' is not a plain filename. Use a name like 'accounts.py' (no folders, no '..').")
    root = SANDBOX_DIR.resolve()
    path = (root / name).resolve()          # follows symlinks
    if path.parent != root:                 # must still be directly inside the sandbox
        raise ValueError(f"'{filename}' points outside the sandbox.")
    return path


def reset_sandbox() -> None:
    """Wipe the sandbox and re-initialize it as a fresh uv project with gradio."""
    if SANDBOX_DIR.exists():
        shutil.rmtree(SANDBOX_DIR)
    SANDBOX_DIR.mkdir(parents=True)

    # --no-workspace: sandbox/ sits inside this crewAI project, so without it uv makes the sandbox a *member of the
    # crew's workspace* (adds [tool.uv.workspace] to ../pyproject.toml) and the two share the crew's .venv: adding
    # gradio then re-syncs that .venv for the sandbox and deletes crewAI/openai/httpcore while the crew is running.
    subprocess.run(["uv", "init", "--bare", "--no-workspace", "--python", "3.13"], cwd=SANDBOX_DIR, check=True)
    # --bare writes no .python-version, so `uv add` would build .venv with the newest Python on this machine; pin it to
    # 3.13, the version of the Docker image the code runs in (ghcr.io/astral-sh/uv:python3.13-bookworm-slim).
    subprocess.run(["uv", "python", "pin", "3.13"], cwd=SANDBOX_DIR, check=True)
    subprocess.run(["uv", "add", "--no-workspace", "gradio"], cwd=SANDBOX_DIR, check=True)

@tool("List Sandbox Files")
def list_sandbox_files() -> str:
    """
    List the filenames currently in the sandbox directory.

    Returns:
        A newline-separated list of filenames, or a message if the
        sandbox is empty.
    """
    names = sorted(p.name for p in SANDBOX_DIR.iterdir())
    return "\n".join(names) if names else "The sandbox is empty."


@tool("Read Sandbox File")
def read_sandbox_file(filename: str) -> str:
    """
    Read and return the text contents of a file in the sandbox directory.

    Args:
        filename: The name of the file to read (e.g. "solution.py").
    Returns:
        The file's contents, or a message if the file does not exist.
    """
    try:
        path = _safe_path(filename)
    except ValueError as e:
        return f"Error: {e}"
    if not path.is_file():
        return f"No such file in the sandbox: {filename}"
    text = path.read_text(errors="replace")
    return text if len(text) <= MAX_READ_CHARS else text[:MAX_READ_CHARS] + f"\n... [truncated, {len(text)} chars]"


@tool("Write Sandbox File")
def write_sandbox_file(filename: str, content: str) -> str:
    """
    Write text to a file in the sandbox directory, replacing any existing
    file with the same name.

    Args:
        filename: The name of the file to write (e.g. "solution.py").
        content: The text content to write.
    Returns:
        A confirmation message.
    """
    try:
        path = _safe_path(filename)
    except ValueError as e:
        return f"Error: {e}"
    if path.name in PROTECTED:
        return f"Error: {filename} belongs to the sandbox's uv project and can't be changed."
    path.write_text(content)
    return f"Wrote {len(content)} characters to {filename}."


@tool("Run Sandbox Python File")
def run_sandbox_python(filename: str) -> str:
    """
    Execute a Python file from the sandbox directory inside an ephemeral
    Docker container, with the sandbox mounted as the working directory,
    using `uv run` to run the code in the uv project.

    Returns the exit code, stdout, and stderr, clearly labeled. Note that
    Python's unittest module prints test results — including failures and
    tracebacks — to stderr by default, not stdout, so stderr is just as
    important as stdout for understanding what happened.

    Args:
        filename: The name of the Python file to run (e.g. "solution.py").
    Returns:
        A labeled block containing the exit code, stdout, and stderr.
    """
    try:
        filename = _safe_path(filename).name
    except ValueError as e:
        return f"Error: {e}"
    try:
        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", f"{SANDBOX_DIR}:/workspace",
                "-w", "/workspace",
                "ghcr.io/astral-sh/uv:python3.13-bookworm-slim",
                "uv", "run", filename,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        return (
            f"Exit code: {result.returncode}\n\n"
            f"--- stdout ---\n{result.stdout or '(empty)'}\n\n"
            f"--- stderr ---\n{result.stderr or '(empty)'}"
        )
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        return (
            "The script timed out after 300 seconds.\n\n"
            f"--- stdout so far ---\n{stdout or '(empty)'}\n\n"
            f"--- stderr so far ---\n{stderr or '(empty)'}"
        )

sandbox_tools = [list_sandbox_files, read_sandbox_file, write_sandbox_file, run_sandbox_python]


def _never_cache(*_args, **_kwargs) -> bool:
    return False


# Sandbox state changes between calls (files appear/change/run), so caching tool
# results would feed agents stale data. Opt out of CrewAI's default tool caching.
for _t in sandbox_tools:
    _t.cache_function = _never_cache