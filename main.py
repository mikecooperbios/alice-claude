import logging

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

import storage
from routers import logs, projects, templates

storage.init_db()

app = FastAPI(title="Agent Team", description="AI-команда разработки с оркестрацией")

app.include_router(projects.router)
app.include_router(templates.router)
app.include_router(logs.router)


@app.get("/health")
def health():
    return {"status": "ok"}
