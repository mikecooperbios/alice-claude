"""File system tools for agents — sandboxed to /workspace/{project_id}/"""
import os
import subprocess
from pathlib import Path
from typing import Optional

WORKSPACE_BASE = Path(os.getenv("WORKSPACE_BASE", "/workspace"))

TOOL_SCHEMAS = [
    {
        "name": "read_file",
        "description": "Прочитать содержимое файла из workspace проекта",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Путь относительно корня workspace проекта"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Записать содержимое в файл в workspace проекта (директории создаются автоматически)",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_command",
        "description": "Выполнить shell-команду в workspace проекта. Возвращает stdout, stderr, exit_code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell-команда (python, pytest, npm, docker compose и т.д.)"},
                "cwd": {"type": "string", "description": "Поддиректория внутри workspace (опционально)"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "list_directory",
        "description": "Получить список файлов и папок в директории workspace",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Путь относительно корня workspace (по умолчанию корень)"},
            },
            "required": [],
        },
    },
]


def _resolve(project_id: str, rel_path: str) -> Path:
    """Resolve a relative path within the project workspace, enforcing sandbox."""
    base = (WORKSPACE_BASE / project_id).resolve()
    target = (base / rel_path).resolve()
    if not str(target).startswith(str(base)):
        raise PermissionError(f"Path '{rel_path}' escapes workspace sandbox")
    return target


def run_tool(name: str, inp: dict, project_id: str) -> str:
    try:
        if name == "read_file":
            path = _resolve(project_id, inp["path"])
            if not path.exists():
                return f"Error: file not found: {inp['path']}"
            return path.read_text(encoding="utf-8", errors="replace")

        if name == "write_file":
            path = _resolve(project_id, inp["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(inp["content"], encoding="utf-8")
            return f"Written {len(inp['content'])} chars to {inp['path']}"

        if name == "run_command":
            base = (WORKSPACE_BASE / project_id).resolve()
            base.mkdir(parents=True, exist_ok=True)
            cwd = _resolve(project_id, inp["cwd"]) if inp.get("cwd") else base
            result = subprocess.run(
                inp["command"],
                shell=True,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=60,
            )
            return (
                f"exit_code: {result.returncode}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            ).strip()

        if name == "list_directory":
            rel = inp.get("path", ".")
            path = _resolve(project_id, rel)
            path.mkdir(parents=True, exist_ok=True)
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
            lines = [
                f"{'[dir] ' if e.is_dir() else '[file]'} {e.name}"
                for e in entries
            ]
            return "\n".join(lines) if lines else "(empty)"

    except PermissionError as e:
        return f"Permission error: {e}"
    except subprocess.TimeoutExpired:
        return "Error: command timed out (60s)"
    except Exception as e:
        return f"Error: {e}"

    return f"Error: unknown fs tool: {name}"
