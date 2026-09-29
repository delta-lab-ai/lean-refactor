"""
Lean project setup: use existing Lean projects under workspace and build each one.
"""

import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], cwd: str | None = None, desc: str = "") -> None:
    """Run a command, printing output and raising on failure."""
    print(f"[info] {desc or ' '.join(cmd)}")
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed (exit {result.returncode}): {' '.join(cmd)}\n"
            f"stderr: {result.stderr}"
        )


def _is_lean_project_dir(path: Path) -> bool:
    """Return True if a directory appears to be a Lean project root."""
    if not path.is_dir():
        return False
    return (
        (path / "lakefile.lean").exists()
        or (path / "lakefile.toml").exists()
        or (path / "lean-toolchain").exists()
    )


def setup_lean_project(workspace_dir: str) -> None:
    """
    Build all existing Lean projects under workspace_dir.

    Args:
        workspace_dir: Directory containing Lean project subdirectories

    Steps:
        1. discover immediate Lean project subdirectories
        2. for each project: run lake exe cache get, then lake build
        3. stop immediately on first failure
    """
    workspace = Path(workspace_dir).resolve()
    if not workspace.exists() or not workspace.is_dir():
        raise RuntimeError(f"Workspace directory not found: {workspace}")

    project_dirs = sorted(
        [p for p in workspace.iterdir() if _is_lean_project_dir(p)],
        key=lambda p: p.name,
    )
    if not project_dirs:
        raise RuntimeError(
            f"No Lean projects found in immediate subdirectories of {workspace}."
        )

    print(f"[info] Found {len(project_dirs)} Lean project(s) in {workspace}.")
    successful_projects: list[str] = []

    for project_path in project_dirs:
        print(f"[info] Building project: {project_path.name}")
        try:
            _run(
                ["lake", "exe", "cache", "get"],
                cwd=str(project_path),
                desc=f"[{project_path.name}] Downloading cached oleans...",
            )
            _run(
                ["lake", "build"],
                cwd=str(project_path),
                desc=f"[{project_path.name}] Building Lean project...",
            )
            successful_projects.append(project_path.name)
        except RuntimeError as e:
            if successful_projects:
                print("[info] Successfully built projects before failure:")
                for name in successful_projects:
                    print(f"  - {name}")
            else:
                print("[info] No projects were built successfully before failure.")
            raise RuntimeError(f"[{project_path.name}] setup failed: {e}") from e

    print("[info] Successfully built projects:")
    for name in successful_projects:
        print(f"  - {name}")
    print(f"[info] Lean projects setup complete in {workspace}")
