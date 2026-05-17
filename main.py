import logging
import os
import re
from collections import defaultdict

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = (
    "Ты Claude — голосовой ассистент, созданный компанией Anthropic. "
    "Ты работаешь через колонку Яндекс Станция. "
    "Никогда не называй себя Алисой и не говори, что ты создан Яндексом. "
    "Отвечай кратко и разговорно, как в живом диалоге. "
    "Никогда не используй списки, маркдаун, символы вроде *, #, —, » или скобки. "
    "Пиши цифры словами. Максимум 2-3 коротких предложения."
)

_LINK_RE = re.compile(r"\[([^\]]*?)\]\(.*?\)", re.DOTALL)
_MARKDOWN_RE = re.compile(r"[*#`_~>|\\]|```.*?```", re.DOTALL)
_EXTRA_SPACES_RE = re.compile(r" {2,}")


def clean_for_tts(text: str) -> str:
    text = _LINK_RE.sub(r"\1", text)  # [label](url) → label
    text = _MARKDOWN_RE.sub("", text)
    text = _EXTRA_SPACES_RE.sub(" ", text)
    return text.strip()


# session_id -> list of {"role": ..., "content": ...}
sessions: dict[str, list[dict]] = defaultdict(list)


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL}


@app.post("/alice")
async def alice_webhook(request: Request):
    body = await request.json()

    session = body.get("session", {})
    session_id: str = session.get("session_id", "")
    is_new: bool = session.get("new", False)
    request_body = body.get("request", {})
    utterance: str = request_body.get("original_utterance", "").strip()
    version: str = body.get("version", "1.0")

    logger.info("session_id=%s new=%s utterance=%r", session_id, is_new, utterance)

    if is_new:
        sessions[session_id] = []

    if not utterance:
        reply_text = "Привет! Я слушаю тебя. Спроси что-нибудь."
        tts_text = reply_text
    else:
        sessions[session_id].append({"role": "user", "content": utterance})

        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=300,
                system=SYSTEM_PROMPT,
                messages=sessions[session_id],
            )
            reply_text = response.content[0].text.strip()
            tts_text = clean_for_tts(reply_text)
            sessions[session_id].append({"role": "assistant", "content": reply_text})
            logger.info(
                "model=%s session=%s reply=%r",
                response.model,
                session_id,
                tts_text,
            )
        except Exception as exc:
            logger.error("Claude API error: %s", exc)
            reply_text = "Произошла ошибка, попробуй ещё раз."
            tts_text = reply_text

    return JSONResponse(
        content={
            "version": version,
            "session": session,
            "response": {
                "text": reply_text,
                "tts": tts_text,
                "end_session": False,
            },
        }
    )
