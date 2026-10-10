"""Read-only endpoint for TP-050 AI suggestions."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.application.decomposition import (
    DecompositionAssistant, DecompositionResponse, suggest_decomposition,
)
from app.application.uow import UnitOfWork
from app.config import get_settings
from app.infrastructure.openai_decomposition import (
    DecompositionNotConfigured, DecompositionUnavailable, OpenAIDecompositionAssistant,
)
from app.infrastructure.uow import get_uow
from app.server.errors import invoke

router = APIRouter(prefix="/api/tasks", tags=["decomposition"])


def get_decomposition_assistant() -> DecompositionAssistant:
    return OpenAIDecompositionAssistant(get_settings())


@router.post("/{task_id}/decomposition-suggestions", response_model=DecompositionResponse)
def suggest(
    task_id: UUID,
    uow: UnitOfWork = Depends(get_uow),
    assistant: DecompositionAssistant = Depends(get_decomposition_assistant),
) -> DecompositionResponse:
    try:
        return invoke(lambda: suggest_decomposition(uow, task_id, assistant))
    except DecompositionNotConfigured as exc:
        raise HTTPException(status_code=503, detail="OpenAI assistance is not configured") from exc
    except DecompositionUnavailable as exc:
        raise HTTPException(status_code=502, detail="AI decomposition is unavailable") from exc
