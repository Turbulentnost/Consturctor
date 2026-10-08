from fastapi import APIRouter

from app.sdk.runner import sdk_status

router = APIRouter()


@router.get("/sdk")
def get_sdk() -> dict[str, object]:
    return sdk_status()
