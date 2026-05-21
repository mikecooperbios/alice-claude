#!/usr/bin/env python3
"""
team — CLI для управления AI-командой разработки.

Установка:
  export AGENT_TEAM_URL=http://localhost:8001
  alias team="python ~/agent-team/team.py"
"""
import json
import os
import sys
from pathlib import Path
from typing import Optional

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

BASE_URL = os.getenv("AGENT_TEAM_URL", "http://localhost:8001").rstrip("/")
STATE_FILE = Path.home() / ".agent-team-state.json"
console = Console()


def _input(prompt: str = "") -> str:
    if prompt:
        sys.stdout.write(prompt)
        sys.stdout.flush()
    return sys.stdin.buffer.readline().decode("utf-8", errors="replace").rstrip("\n")


# ── State management ──────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _current_id() -> Optional[str]:
    return _load_state().get("current_project_id")


def _set_current(pid: str) -> None:
    state = _load_state()
    state["current_project_id"] = pid
    _save_state(state)


# ── HTTP helpers ──────────────────────────────

def _get(path: str) -> dict | list:
    try:
        r = httpx.get(f"{BASE_URL}{path}", timeout=300)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        console.print(f"[red]Не удалось подключиться к {BASE_URL}. Сервер запущен?[/red]")
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        console.print(f"[red]HTTP {e.response.status_code}: {e.response.text}[/red]")
        sys.exit(1)


def _post(path: str, body: dict) -> dict:
    try:
        r = httpx.post(f"{BASE_URL}{path}", json=body, timeout=300)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        console.print(f"[red]Не удалось подключиться к {BASE_URL}. Сервер запущен?[/red]")
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        console.print(f"[red]HTTP {e.response.status_code}: {e.response.text}[/red]")
        sys.exit(1)


def _put(path: str, body: dict) -> dict:
    try:
        r = httpx.put(f"{BASE_URL}{path}", json=body, timeout=60)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        console.print(f"[red]Не удалось подключиться к {BASE_URL}.[/red]")
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        console.print(f"[red]HTTP {e.response.status_code}: {e.response.text}[/red]")
        sys.exit(1)


# ── Rendering ─────────────────────────────────

_STATUS_COLOR = {
    "planning": "yellow",
    "in_progress": "cyan",
    "review": "blue",
    "done": "green",
    "failed": "red",
    "pending": "dim",
}


def _color_status(status: str) -> str:
    color = _STATUS_COLOR.get(status, "white")
    return f"[{color}]{status}[/{color}]"


def _print_plan(data: dict) -> None:
    project = data.get("project", data)
    msg = data.get("teamlead_message", "")

    console.print(Panel(
        f"[bold]{project['idea']}[/bold]\n\n"
        f"ID: [dim]{project['id']}[/dim]\n"
        f"Статус: {_color_status(project['status'])}",
        title="[bold cyan]Проект создан[/bold cyan]",
        border_style="cyan",
    ))

    tasks = project.get("tasks", [])
    if tasks:
        t = Table(show_header=True, header_style="bold")
        t.add_column("Роль", style="cyan", width=12)
        t.add_column("Задача")
        t.add_column("Статус", width=12)
        for task in tasks:
            t.add_row(task["role"], task["title"], _color_status(task["status"]))
        console.print(t)

    if msg:
        console.print(Panel(msg, title="[bold]Тимлид[/bold]", border_style="yellow"))


def _print_status(project: dict) -> None:
    tasks = project.get("tasks", [])
    done = sum(1 for t in tasks if t["status"] == "done")
    total = len(tasks)

    console.print(Panel(
        f"[bold]{project['idea']}[/bold]\n"
        f"Статус: {_color_status(project['status'])}  |  "
        f"Задачи: {done}/{total}",
        title=f"[dim]{project['id'][:8]}...[/dim]",
        border_style="blue",
    ))

    if tasks:
        t = Table(show_header=True, header_style="bold")
        t.add_column("Роль", style="cyan", width=12)
        t.add_column("Задача")
        t.add_column("Статус", width=14)
        t.add_column("Результат (кратко)", max_width=50)
        for task in tasks:
            result_preview = ""
            if task.get("result"):
                result_preview = task["result"][:80].replace("\n", " ")
            t.add_row(task["role"], task["title"],
                      _color_status(task["status"]), result_preview)
        console.print(t)


# ── Commands ──────────────────────────────────

def cmd_new(idea: str) -> None:
    """Создать проект и получить план от тимлида."""
    console.print(f"[cyan]Тимлид декомпозирует задачу...[/cyan]")
    data = _post("/projects", {"idea": idea})
    project = data.get("project", data)
    _set_current(project["id"])
    _print_plan(data)

    console.print()
    answer = _input("Одобрить план? [y/n/фидбек]: ").strip()
    if answer.lower() in ("y", "да", "yes", ""):
        cmd_approve()
    elif answer.lower() in ("n", "нет", "no"):
        console.print("[yellow]Отклонено без комментариев.[/yellow]")
        feedback = _input("Что изменить (Enter = пропустить): ").strip()
        cmd_reject(feedback or "Пользователь отклонил план")
    else:
        cmd_reject(answer)


def cmd_approve(project_id: Optional[str] = None) -> None:
    """Одобрить план текущего проекта."""
    pid = project_id or _current_id()
    if not pid:
        console.print("[red]Нет активного проекта. Используй: team new <идея>[/red]")
        return
    console.print("[cyan]Запускаю выполнение...[/cyan]")
    data = _post(f"/projects/{pid}/approve", {"approved": True})
    _print_plan(data)


def cmd_reject(feedback: str, project_id: Optional[str] = None) -> None:
    """Отклонить план с фидбеком."""
    pid = project_id or _current_id()
    if not pid:
        console.print("[red]Нет активного проекта.[/red]")
        return
    console.print("[cyan]Тимлид пересматривает план...[/cyan]")
    data = _post(f"/projects/{pid}/approve", {"approved": False, "feedback": feedback})
    _print_plan(data)

    console.print()
    answer = _input("Одобрить новый план? [y/n/фидбек]: ").strip()
    if answer.lower() in ("y", "да", "yes", ""):
        cmd_approve(pid)
    elif answer.lower() not in ("n", "нет", "no") and answer:
        cmd_reject(answer, pid)


def cmd_status(project_id: Optional[str] = None) -> None:
    """Показать статус и задачи проекта."""
    pid = project_id or _current_id()
    if not pid:
        console.print("[red]Нет активного проекта.[/red]")
        return
    project = _get(f"/projects/{pid}")
    _print_status(project)


def cmd_chat(project_id: Optional[str] = None) -> None:
    """Интерактивный REPL с тимлидом."""
    pid = project_id or _current_id()
    if not pid:
        console.print("[red]Нет активного проекта. Используй: team new <идея>[/red]")
        return

    project = _get(f"/projects/{pid}")
    console.print(Panel(
        f"[bold]{project['idea']}[/bold]  |  {_color_status(project['status'])}",
        title="[cyan]Чат с тимлидом[/cyan]",
    ))
    console.print("[dim]Введи сообщение. Ctrl+C или 'exit' для выхода.[/dim]\n")

    while True:
        try:
            msg = _input("[teamlead]> ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Выход из чата.[/dim]")
            break
        if msg.lower() in ("exit", "quit", "выход", ""):
            break
        data = _post(f"/projects/{pid}/chat", {"message": msg})
        console.print(Panel(data.get("reply", ""), border_style="yellow"))


def cmd_hr() -> None:
    """Интерактивный REPL с HR-агентом."""
    console.print(Panel(
        "HR управляет шаблонами агентов. Можно создавать новых агентов,\n"
        "редактировать промпты и применять фидбек от тимлида.",
        title="[magenta]HR — управление агентами[/magenta]",
    ))
    console.print("[dim]Ctrl+C или 'exit' для выхода.[/dim]\n")

    while True:
        try:
            msg = _input("[hr]> ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Выход из HR-сессии.[/dim]")
            break
        if msg.lower() in ("exit", "quit", "выход", ""):
            break
        data = _post("/templates/hr/chat", {"message": msg})
        console.print(Panel(data.get("reply", ""), border_style="magenta"))


def cmd_logs(project_id: Optional[str] = None) -> None:
    """Показать лог активности проекта."""
    pid = project_id or _current_id()
    if not pid:
        logs = _get("/logs")
    else:
        logs = _get(f"/projects/{pid}/logs")

    if not logs:
        console.print("[dim]Нет записей в логе.[/dim]")
        return

    t = Table(show_header=True, header_style="bold")
    t.add_column("Время", style="dim", width=20)
    t.add_column("Роль", style="cyan", width=12)
    t.add_column("Уровень", width=8)
    t.add_column("Сообщение")

    level_color = {"info": "white", "warning": "yellow", "error": "red"}
    for entry in reversed(logs):
        ts = entry["created_at"][:19].replace("T", " ")
        level = entry["level"]
        color = level_color.get(level, "white")
        t.add_row(ts, entry["role"], f"[{color}]{level}[/{color}]", entry["message"])

    console.print(t)


def cmd_ls() -> None:
    """Список всех проектов."""
    projects = _get("/projects")
    if not projects:
        console.print("[dim]Проектов нет. Начни с: team new <идея>[/dim]")
        return

    current = _current_id()
    t = Table(show_header=True, header_style="bold")
    t.add_column("", width=2)
    t.add_column("ID", style="dim", width=10)
    t.add_column("Идея")
    t.add_column("Статус", width=14)
    t.add_column("Создан", width=12)

    for p in projects:
        marker = "▶" if p["id"] == current else ""
        t.add_row(
            marker,
            p["id"][:8],
            p["idea"][:60],
            _color_status(p["status"]),
            p["created_at"][:10],
        )
    console.print(t)


def cmd_switch(project_id: str) -> None:
    """Переключиться на другой проект."""
    p = _get(f"/projects/{project_id}")
    _set_current(project_id)
    console.print(f"[green]Активный проект: {p['idea'][:60]}[/green]")


def cmd_agents() -> None:
    """Список всех агентов."""
    templates = _get("/templates")
    t = Table(show_header=True, header_style="bold")
    t.add_column("Роль", style="cyan", width=14)
    t.add_column("Имя", width=20)
    t.add_column("Промпт (начало)")
    for tmpl in templates:
        preview = tmpl["system_prompt"][:80].replace("\n", " ")
        t.add_row(tmpl["role"], tmpl["name"], preview)
    console.print(t)


def cmd_template_show(role: str) -> None:
    """Показать полный промпт агента."""
    tmpl = _get(f"/templates/{role}")
    console.print(Panel(
        tmpl["system_prompt"],
        title=f"[cyan]{tmpl['name']} ({role})[/cyan]",
    ))


def cmd_template_edit(role: str) -> None:
    """Открыть промпт агента в $EDITOR."""
    import tempfile, subprocess
    tmpl = _get(f"/templates/{role}")
    editor = os.getenv("EDITOR", "nano")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(tmpl["system_prompt"])
        tmp_path = f.name

    subprocess.call([editor, tmp_path])

    new_prompt = Path(tmp_path).read_text()
    Path(tmp_path).unlink()

    if new_prompt.strip() == tmpl["system_prompt"].strip():
        console.print("[dim]Без изменений.[/dim]")
        return

    _put(f"/templates/{role}", {"system_prompt": new_prompt})
    console.print(f"[green]Промпт [{role}] обновлён.[/green]")


# ── Entry point ───────────────────────────────

def _usage() -> None:
    console.print(Panel(
        "[bold]Команды:[/bold]\n\n"
        "  [cyan]team new[/cyan] <идея>            — Создать проект, получить план, одобрить\n"
        "  [cyan]team chat[/cyan] [id]              — Чат с тимлидом\n"
        "  [cyan]team approve[/cyan] [id]           — Одобрить план\n"
        "  [cyan]team reject[/cyan] <фидбек> [id]  — Отклонить план с комментарием\n"
        "  [cyan]team status[/cyan] [id]            — Прогресс задач\n"
        "  [cyan]team logs[/cyan] [id]              — Лог активности\n"
        "  [cyan]team ls[/cyan]                     — Список проектов\n"
        "  [cyan]team switch[/cyan] <id>            — Сменить активный проект\n\n"
        "  [magenta]team hr[/magenta]                       — Чат с HR (создание/редактирование агентов)\n"
        "  [magenta]team agents[/magenta]                   — Список агентов\n"
        "  [magenta]team template[/magenta] <роль>          — Показать промпт агента\n"
        "  [magenta]team template edit[/magenta] <роль>     — Редактировать промпт в $EDITOR\n\n"
        "[dim]AGENT_TEAM_URL по умолчанию: http://localhost:8001[/dim]",
        title="[bold]team[/bold] — управление AI-командой",
        border_style="cyan",
    ))


def main() -> None:
    args = sys.argv[1:]
    if not args:
        _usage()
        return

    cmd = args[0]

    if cmd == "new":
        if len(args) < 2:
            console.print("[red]Укажи идею: team new <идея>[/red]")
            return
        cmd_new(" ".join(args[1:]))

    elif cmd == "chat":
        cmd_chat(args[1] if len(args) > 1 else None)

    elif cmd == "approve":
        cmd_approve(args[1] if len(args) > 1 else None)

    elif cmd == "reject":
        if len(args) < 2:
            console.print("[red]Укажи фидбек: team reject <комментарий>[/red]")
            return
        possible_id = args[-1] if len(args) > 2 and len(args[-1]) > 30 else None
        feedback_parts = args[1:-1] if possible_id else args[1:]
        cmd_reject(" ".join(feedback_parts), possible_id)

    elif cmd == "status":
        cmd_status(args[1] if len(args) > 1 else None)

    elif cmd == "logs":
        cmd_logs(args[1] if len(args) > 1 else None)

    elif cmd == "ls":
        cmd_ls()

    elif cmd == "switch":
        if len(args) < 2:
            console.print("[red]Укажи ID: team switch <id>[/red]")
            return
        cmd_switch(args[1])

    elif cmd == "hr":
        cmd_hr()

    elif cmd == "agents":
        cmd_agents()

    elif cmd == "template":
        if len(args) < 2:
            cmd_agents()
        elif len(args) == 2:
            cmd_template_show(args[1])
        elif args[1] == "edit" and len(args) == 3:
            cmd_template_edit(args[2])
        else:
            console.print("[red]Использование: team template <роль> | team template edit <роль>[/red]")

    else:
        console.print(f"[red]Неизвестная команда: {cmd}[/red]")
        _usage()


if __name__ == "__main__":
    main()
