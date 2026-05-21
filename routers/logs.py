from fastapi import APIRouter, Query

import storage

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("")
def get_logs(limit: int = Query(100, ge=1, le=500)):
    return storage.get_logs(limit=limit)
