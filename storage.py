import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path("data.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id               TEXT PRIMARY KEY,
                idea             TEXT NOT NULL,
                status           TEXT NOT NULL DEFAULT 'planning',
                plan_json        TEXT,
                result           TEXT,
                notion_page_id   TEXT,
                workspace_path   TEXT,
                created_at       TEXT NOT NULL,
                updated_at       TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id          TEXT PRIMARY KEY,
                project_id  TEXT NOT NULL REFERENCES projects(id),
                title       TEXT NOT NULL,
                description TEXT NOT NULL,
                role        TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',
                result      TEXT,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS templates (
                role          TEXT PRIMARY KEY,
                name          TEXT NOT NULL,
                system_prompt TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  TEXT,
                task_id     TEXT,
                role        TEXT NOT NULL,
                level       TEXT NOT NULL DEFAULT 'info',
                message     TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );
        """)
    _seed_templates()


_DEFAULT_TEMPLATES = {
    "teamlead": {
        "name": "Team Lead",
        "system_prompt": (
            "Ты опытный технический тимлид. Твои задачи:\n"
            "1. ДЕКОМПОЗИЦИЯ: получая идею, разбиваешь её на конкретные задачи для исполнителей "
            "(backend, frontend, architect, tester). Для каждой задачи — чёткое название и описание.\n"
            "2. ПЛАНИРОВАНИЕ: создаёшь задачи через create_task, сохраняешь план через save_plan_summary, "
            "публикуешь план в Notion через notion_add_comment для согласования с пользователем.\n"
            "3. КООРДИНАЦИЯ: после одобрения следишь за прогрессом, логируешь важные шаги.\n"
            "4. РЕВЬЮ: проверяешь результаты каждого исполнителя, при необходимости отмечаешь проблемы в логе.\n"
            "5. СБОРКА: агрегируешь результаты в единый финальный документ, публикуешь в Notion.\n"
            "Используй все доступные инструменты. Можешь читать и запускать код в workspace."
        ),
    },
    "backend": {
        "name": "Backend Developer",
        "system_prompt": (
            "Ты senior backend разработчик. Получаешь конкретную задачу и:\n"
            "- Пишешь рабочий код в workspace (Python/Node/Go — по контексту задачи)\n"
            "- Определяешь структуру файлов через list_directory и write_file\n"
            "- Запускаешь тесты через run_command\n"
            "- Документируешь ключевые API endpoints и решения\n"
            "Сохрани финальный результат через save_result с описанием что сделано и где лежат файлы."
        ),
    },
    "frontend": {
        "name": "Frontend Developer",
        "system_prompt": (
            "Ты senior frontend разработчик. Получаешь конкретную задачу и:\n"
            "- Пишешь компоненты в workspace (React/Vue — по контексту)\n"
            "- Создаёшь файлы через write_file, проверяешь через run_command\n"
            "- Описываешь UI/UX решения и интеграцию с API\n"
            "Сохрани финальный результат через save_result с описанием что сделано."
        ),
    },
    "architect": {
        "name": "Software Architect",
        "system_prompt": (
            "Ты software architect. Получаешь задачу и:\n"
            "- Проектируешь архитектуру системы\n"
            "- Пишешь ADR (Architecture Decision Record) в workspace через write_file\n"
            "- Описываешь компоненты, их взаимодействие, риски и trade-offs\n"
            "- Даёшь рекомендации по стеку\n"
            "Сохрани финальный результат через save_result."
        ),
    },
    "tester": {
        "name": "QA Engineer",
        "system_prompt": (
            "Ты QA инженер. Получаешь задачу/код и:\n"
            "- Читаешь код в workspace через read_file и list_directory\n"
            "- Пишешь тесты в workspace через write_file\n"
            "- Запускаешь тесты через run_command и анализируешь результат\n"
            "- Составляешь отчёт о найденных проблемах\n"
            "Сохрани финальный результат через save_result."
        ),
    },
    "hr": {
        "name": "HR / Prompt Engineer",
        "system_prompt": (
            "Ты HR и prompt engineer команды. Управляешь шаблонами агентов.\n"
            "Можешь просматривать (list_templates, get_template) и редактировать "
            "системные промпты (update_template) для улучшения качества работы.\n"
            "При редактировании сохраняй суть роли, улучшай чёткость инструкций.\n"
            "Всегда используй инструменты — не выдумывай содержимое шаблонов."
        ),
    },
}


def _seed_templates() -> None:
    with get_conn() as conn:
        for role, data in _DEFAULT_TEMPLATES.items():
            conn.execute(
                "INSERT OR IGNORE INTO templates (role, name, system_prompt, updated_at) VALUES (?,?,?,?)",
                (role, data["name"], data["system_prompt"], _now()),
            )


# ── Projects ──────────────────────────────────

def create_project(idea: str) -> dict:
    pid = str(uuid.uuid4())
    now = _now()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO projects (id, idea, status, created_at, updated_at) VALUES (?,?,?,?,?)",
            (pid, idea, "planning", now, now),
        )
    return get_project(pid)


def get_project(pid: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["plan"] = json.loads(d.pop("plan_json")) if d.get("plan_json") else None
    d["tasks"] = get_tasks(pid)
    return d


def update_project(pid: str, **kwargs) -> None:
    if "plan" in kwargs:
        kwargs["plan_json"] = json.dumps(kwargs.pop("plan"), ensure_ascii=False)
    kwargs["updated_at"] = _now()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [pid]
    with get_conn() as conn:
        conn.execute(f"UPDATE projects SET {sets} WHERE id=?", vals)


def list_projects() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


# ── Tasks ─────────────────────────────────────

def create_task(project_id: str, title: str, description: str, role: str) -> dict:
    tid = str(uuid.uuid4())
    now = _now()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO tasks (id, project_id, title, description, role, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (tid, project_id, title, description, role, "pending", now, now),
        )
    return get_task(tid)


def get_task(tid: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    return dict(row) if row else None


def get_tasks(project_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE project_id=? ORDER BY created_at",
            (project_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_task(tid: str, **kwargs) -> None:
    kwargs["updated_at"] = _now()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [tid]
    with get_conn() as conn:
        conn.execute(f"UPDATE tasks SET {sets} WHERE id=?", vals)


def clear_project_tasks(project_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM tasks WHERE project_id=?", (project_id,))


# ── Templates ─────────────────────────────────

def get_template(role: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM templates WHERE role=?", (role,)).fetchone()
    return dict(row) if row else None


def update_template(role: str, system_prompt: str, name: Optional[str] = None) -> Optional[dict]:
    with get_conn() as conn:
        if name:
            conn.execute(
                "UPDATE templates SET system_prompt=?, name=?, updated_at=? WHERE role=?",
                (system_prompt, name, _now(), role),
            )
        else:
            conn.execute(
                "UPDATE templates SET system_prompt=?, updated_at=? WHERE role=?",
                (system_prompt, _now(), role),
            )
    return get_template(role)


def list_templates() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM templates ORDER BY role").fetchall()
    return [dict(r) for r in rows]


# ── Logs ──────────────────────────────────────

def add_log(
    role: str,
    message: str,
    level: str = "info",
    project_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO logs (project_id, task_id, role, level, message, created_at) VALUES (?,?,?,?,?,?)",
            (project_id, task_id, role, level, message, _now()),
        )


def get_logs(project_id: Optional[str] = None, limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        if project_id:
            rows = conn.execute(
                "SELECT * FROM logs WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM logs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]
