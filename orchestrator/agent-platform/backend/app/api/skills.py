from fastapi import APIRouter

from app.skills.registry import list_skills

router = APIRouter()


@router.get("/skills")
def get_skills() -> dict[str, object]:
    return {"items": [item.model_dump() for item in list_skills()]}
