import json
import logging
import os
from typing import Any

import anthropic

import storage
from tools import fs_tools, notion_tools

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


# ── Tool schema sets ───────────────────────────

_BASE_TOOLS = [
    {
        "name": "save_result",
        "description": "Сохранить результат выполнения задачи",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "result": {"type": "string", "description": "Подробный результат работы"},
            },
            "required": ["task_id", "result"],
        },
    },
    {
        "name": "add_log",
        "description": "Добавить запись в лог",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "level": {"type": "string", "enum": ["info", "warning", "error"]},
            },
            "required": ["message"],
        },
    },
]

_TEAMLEAD_EXTRA = [
    {
        "name": "create_task",
        "description": "Создать задачу для исполнителя",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "role": {
                    "type": "string",
                    "enum": ["backend", "frontend", "architect", "tester"],
                },
            },
            "required": ["title", "description", "role"],
        },
    },
    {
        "name": "save_plan_summary",
        "description": "Сохранить краткое описание плана",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
]

_HR_TOOLS = [
    {
        "name": "list_templates",
        "description": "Показать все шаблоны агентов",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_template",
        "description": "Получить текущий шаблон агента",
        "input_schema": {
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "enum": ["teamlead", "backend", "frontend", "architect", "tester", "hr"],
                }
            },
            "required": ["role"],
        },
    },
    {
        "name": "update_template",
        "description": "Обновить системный промпт агента",
        "input_schema": {
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "enum": ["teamlead", "backend", "frontend", "architect", "tester", "hr"],
                },
                "system_prompt": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["role", "system_prompt"],
        },
    },
]


def _tools_for(role: str) -> list[dict]:
    if role == "hr":
        return _HR_TOOLS + notion_tools.TOOL_SCHEMAS
    if role == "teamlead":
        return _BASE_TOOLS + _TEAMLEAD_EXTRA + fs_tools.TOOL_SCHEMAS + notion_tools.TOOL_SCHEMAS
    # backend, frontend, architect, tester
    return _BASE_TOOLS + fs_tools.TOOL_SCHEMAS


# ── Tool dispatch ──────────────────────────────

def _run_tool(role: str, name: str, inp: dict, ctx: dict) -> str:
    project_id = ctx.get("project_id", "")
    task_id = ctx.get("task_id")

    # File system tools
    if name in {"read_file", "write_file", "run_command", "list_directory"}:
        return fs_tools.run_tool(name, inp, project_id)

    # Notion tools
    if name.startswith("notion_"):
        return notion_tools.run_tool(name, inp)

    # Storage tools
    if name == "create_task":
        task = storage.create_task(
            project_id=project_id,
            title=inp["title"],
            description=inp["description"],
            role=inp["role"],
        )
        storage.add_log("teamlead", f"Задача: [{inp['role']}] {inp['title']}", project_id=project_id)
        return json.dumps({"task_id": task["id"]})

    if name == "save_plan_summary":
        storage.update_project(project_id, plan={"summary": inp["summary"]})
        return json.dumps({"status": "saved"})

    if name == "save_result":
        if task_id:
            storage.update_task(task_id, result=inp["result"], status="done")
            storage.add_log(role, "Результат сохранён", project_id=project_id, task_id=task_id)
        else:
            storage.update_project(project_id, result=inp["result"])
            storage.add_log("teamlead", "Финальный результат сохранён", project_id=project_id)
        return json.dumps({"status": "saved"})

    if name == "add_log":
        storage.add_log(role, inp["message"], level=inp.get("level", "info"),
                        project_id=project_id, task_id=task_id)
        return json.dumps({"status": "logged"})

    if name == "list_templates":
        return json.dumps(storage.list_templates())

    if name == "get_template":
        return json.dumps(storage.get_template(inp["role"]))

    if name == "update_template":
        updated = storage.update_template(inp["role"], inp["system_prompt"], inp.get("name"))
        storage.add_log("hr", f"Шаблон обновлён: {inp['role']}")
        return json.dumps({"status": "updated", "template": updated})

    return json.dumps({"error": f"unknown tool: {name}"})


# ── Core runner ────────────────────────────────

def run_agent(role: str, prompt: str, ctx: dict) -> str:
    """Run a role agent and return its final text response."""
    template = storage.get_template(role)
    if not template:
        raise ValueError(f"No template for role: {role}")

    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    tools = _tools_for(role)
    client = _get_client()

    storage.add_log(role, "Начало работы",
                    project_id=ctx.get("project_id"), task_id=ctx.get("task_id"))

    for _ in range(15):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=template["system_prompt"],
            tools=tools,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            return next((b.text for b in response.content if hasattr(b, "text")), "")

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    logger.info("[%s] %s %s", role, block.name, block.input)
                    result = _run_tool(role, block.name, block.input, ctx)
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": results})

    return next((b.text for b in response.content if hasattr(b, "text")), "")


# ── Orchestration ──────────────────────────────

def decompose_project(project_id: str) -> dict:
    project = storage.get_project(project_id)
    storage.clear_project_tasks(project_id)
    storage.update_project(project_id, status="planning")

    # Ensure workspace exists
    from tools.fs_tools import WORKSPACE_BASE
    (WORKSPACE_BASE / project_id).mkdir(parents=True, exist_ok=True)
    storage.update_project(project_id, workspace_path=str(WORKSPACE_BASE / project_id))

    message = run_agent(
        "teamlead",
        f"Идея проекта: {project['idea']}\n\n"
        "Декомпозируй на задачи: создай каждую через create_task "
        "(роли: architect, backend, frontend, tester — только нужные).\n"
        "Сохрани план через save_plan_summary.\n"
        "Если настроен Notion — создай страницу проекта через notion_create_page, "
        "запиши план через notion_update_page, спроси подтверждение через notion_add_comment.\n"
        "Опиши план пользователю: что будет сделано, кем, в каком порядке.",
        {"project_id": project_id},
    )
    return {"project": storage.get_project(project_id), "teamlead_message": message}


def execute_project(project_id: str) -> dict:
    project = storage.get_project(project_id)
    storage.update_project(project_id, status="in_progress")
    storage.add_log("teamlead", "Выполнение начато", project_id=project_id)

    for task in storage.get_tasks(project_id):
        if task["status"] != "pending":
            continue
        storage.update_task(task["id"], status="in_progress")
        logger.info("Running [%s] %s", task["role"], task["title"])
        try:
            run_agent(
                task["role"],
                f"Задача: {task['title']}\n\nОписание: {task['description']}\n\n"
                f"Рабочая директория проекта: {project.get('workspace_path', '/workspace/' + project_id)}\n"
                f"Используй write_file для сохранения кода, run_command для запуска тестов/команд.\n"
                f"Когда закончишь — сохрани результат через save_result с task_id={task['id']}.",
                {"project_id": project_id, "task_id": task["id"]},
            )
        except Exception as exc:
            logger.error("Task %s failed: %s", task["id"], exc)
            storage.update_task(task["id"], status="failed", result=str(exc))
            storage.add_log(task["role"], f"Ошибка: {exc}", level="error",
                            project_id=project_id, task_id=task["id"])

    storage.update_project(project_id, status="review")
    storage.add_log("teamlead", "Ревью результатов", project_id=project_id)

    tasks = storage.get_tasks(project_id)
    results_block = "\n\n".join(
        f"[{t['role'].upper()}] {t['title']} ({t['status']}):\n{t['result'] or '(нет результата)'}"
        for t in tasks
    )

    message = run_agent(
        "teamlead",
        f"Проект: {project['idea']}\n\n"
        f"Результаты команды:\n{results_block}\n\n"
        "Проверь каждый результат. Собери финальный документ через save_result.\n"
        "Если настроен Notion — опубликуй итог через notion_update_page и notion_add_comment.\n"
        "Представь итог пользователю.",
        {"project_id": project_id},
    )
    storage.update_project(project_id, status="done")
    return {"project": storage.get_project(project_id), "teamlead_message": message}
