from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "archiclaude-backend"}
