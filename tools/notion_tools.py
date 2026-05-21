"""Notion integration — graceful degradation when NOTION_TOKEN is unset."""
import logging
import os

logger = logging.getLogger(__name__)

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_PARENT_PAGE_ID = os.getenv("NOTION_PARENT_PAGE_ID", "")

_client = None


def _get_client():
    global _client
    if not NOTION_TOKEN:
        return None
    if _client is None:
        try:
            from notion_client import Client
            _client = Client(auth=NOTION_TOKEN)
        except ImportError:
            logger.warning("notion-client not installed — Notion integration disabled")
    return _client


TOOL_SCHEMAS = [
    {
        "name": "notion_create_page",
        "description": "Создать страницу проекта в Notion для коммуникации с пользователем",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "idea": {"type": "string"},
            },
            "required": ["title", "idea"],
        },
    },
    {
        "name": "notion_update_page",
        "description": "Добавить раздел с результатами на страницу проекта в Notion",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string"},
                "section_title": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["page_id", "section_title", "content"],
        },
    },
    {
        "name": "notion_add_comment",
        "description": "Написать комментарий на странице проекта (для общения с пользователем)",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["page_id", "text"],
        },
    },
    {
        "name": "notion_get_latest_comment",
        "description": "Прочитать последний комментарий пользователя на странице проекта",
        "input_schema": {
            "type": "object",
            "properties": {"page_id": {"type": "string"}},
            "required": ["page_id"],
        },
    },
]


def run_tool(name: str, inp: dict) -> str:
    client = _get_client()
    if not client:
        return "(Notion отключën — NOTION_TOKEN не задан)"

    try:
        if name == "notion_create_page":
            page = client.pages.create(
                parent={"page_id": NOTION_PARENT_PAGE_ID},
                properties={"title": {"title": [{"text": {"content": inp["title"]}}]}},
                children=[
                    {"object": "block", "type": "heading_2",
                     "heading_2": {"rich_text": [{"text": {"content": "Идея проекта"}}]}},
                    {"object": "block", "type": "paragraph",
                     "paragraph": {"rich_text": [{"text": {"content": inp["idea"]}}]}},
                ],
            )
            return page["id"]

        if name == "notion_update_page":
            client.blocks.children.append(
                inp["page_id"],
                children=[
                    {"object": "block", "type": "heading_3",
                     "heading_3": {"rich_text": [{"text": {"content": inp["section_title"]}}]}},
                    {"object": "block", "type": "paragraph",
                     "paragraph": {"rich_text": [{"text": {"content": inp["content"][:2000]}}]}},
                ],
            )
            return "updated"

        if name == "notion_add_comment":
            client.comments.create(
                parent={"page_id": inp["page_id"]},
                rich_text=[{"text": {"content": inp["text"]}}],
            )
            return "comment posted"

        if name == "notion_get_latest_comment":
            response = client.comments.list(block_id=inp["page_id"])
            results = response.get("results", [])
            if not results:
                return "(нет комментариев)"
            last = results[-1]
            return "".join(t.get("plain_text", "") for t in last.get("rich_text", []))

    except Exception as e:
        logger.error("Notion error in %s: %s", name, e)
        return f"Notion error: {e}"

    return f"unknown notion tool: {name}"
