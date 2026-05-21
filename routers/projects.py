from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import agents
import storage
from tools import notion_tools

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    idea: str


class ProjectApprove(BaseModel):
    approved: bool
    feedback: str = ""


class AgentChat(BaseModel):
    message: str


@router.post("")
def create_project(body: ProjectCreate):
    project = storage.create_project(body.idea)
    return agents.decompose_project(project["id"])


@router.get("")
def list_projects():
    return storage.list_projects()


@router.get("/{project_id}")
def get_project(project_id: str):
    p = storage.get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


@router.post("/{project_id}/approve")
def approve_project(project_id: str, body: ProjectApprove):
    p = storage.get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    if p["status"] not in ("planning",):
        raise HTTPException(400, f"Project status is '{p['status']}', expected 'planning'")

    if body.approved:
        storage.add_log("teamlead", "План одобрен пользователем", project_id=project_id)
        return agents.execute_project(project_id)

    feedback = body.feedback or "Пользователь отклонил план без комментариев"
    storage.add_log("teamlead", f"План отклонён: {feedback}", project_id=project_id)
    storage.clear_project_tasks(project_id)
    storage.update_project(project_id, status="planning")
    message = agents.run_agent(
        "teamlead",
        f"Идея проекта: {p['idea']}\n\n"
        f"Предыдущий план отклонён. Обратная связь: {feedback}\n\n"
        "Пересмотри декомпозицию. Создай задачи через create_task, "
        "сохрани новый план через save_plan_summary.\n"
        "Объясни пользователю что изменилось.",
        {"project_id": project_id},
    )
    return {"project": storage.get_project(project_id), "teamlead_message": message}


@router.get("/{project_id}/logs")
def get_project_logs(project_id: str):
    if not storage.get_project(project_id):
        raise HTTPException(404, "Project not found")
    return storage.get_logs(project_id)


@router.get("/{project_id}/notion-check")
def notion_check(project_id: str):
    p = storage.get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    if not p.get("notion_page_id"):
        return {"comment": None, "message": "No Notion page for this project"}
    comment = notion_tools.run_tool("notion_get_latest_comment", {"page_id": p["notion_page_id"]})
    return {"comment": comment}


@router.post("/{project_id}/chat")
def chat(project_id: str, body: AgentChat):
    if not storage.get_project(project_id):
        raise HTTPException(404, "Project not found")
    reply = agents.run_agent("teamlead", body.message, {"project_id": project_id})
    return {"reply": reply}
