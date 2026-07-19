from fastapi import APIRouter


router = APIRouter(tags=["system"])


@router.get("/")
async def root() -> dict[str, str]:
    """Return basic API information."""
    return {
        "name": "Football API",
        "version": "0.1.0",
        "docs": "/docs",
    }


@router.get("/health")
async def health() -> dict[str, str]:
    """Report whether the API process is ready to receive requests."""
    return {"status": "ok"}
