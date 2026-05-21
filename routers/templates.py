from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

import agents
import storage

router = APIRouter(prefix="/templates", tags=["templates"])


class TemplateUpdate(BaseModel):
    system_prompt: str
    name: Optional[str] = None


class HRChat(BaseModel):
    message: str


@router.get("")
def list_templates():
    return storage.list_templates()


@router.get("/{role}")
def get_template(role: str):
    t = storage.get_template(role)
    if not t:
        raise HTTPException(404, f"Template '{role}' not found")
    return t


@router.put("/{role}")
def update_template(role: str, body: TemplateUpdate):
    if not storage.get_template(role):
        raise HTTPException(404, f"Template '{role}' not found")
    return storage.update_template(role, body.system_prompt, body.name)


@router.post("/hr/chat")
def hr_chat(body: HRChat):
    reply = agents.run_agent("hr", body.message, {})
    return {"reply": reply}
