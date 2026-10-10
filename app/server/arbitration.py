"""Read-only TP-051 endpoint: deterministic options plus optional AI explanation."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.application.arbitration import (
    ArbitrationAssistant, ArbitrationNotConfigured, ArbitrationUnavailable,
    OptionExplanation, explain_week,
)
from app.application.uow import UnitOfWork
from app.config import get_settings
from app.infrastructure.openai_arbitration import OpenAIArbitrationAssistant
from app.infrastructure.uow import get_uow
from app.server.capacity import SelectionRequest
from app.server.errors import invoke
from app.server.planning import ProposalResponse

router = APIRouter(prefix="/api/capacity/weeks", tags=["arbitration"])


class ArbitrationResponse(BaseModel):
    state: Literal["PROPOSED"] = "PROPOSED"
    source: Literal["AI_SUGGESTION"] = "AI_SUGGESTION"
    proposal: ProposalResponse
    explanations: list[OptionExplanation]


def get_arbitration_assistant() -> ArbitrationAssistant:
    return OpenAIArbitrationAssistant(get_settings())


@router.post("/{week_start}/arbitration-suggestions", response_model=ArbitrationResponse)
def suggest_arbitration(
    week_start: date,
    payload: SelectionRequest,
    uow: UnitOfWork = Depends(get_uow),
    assistant: ArbitrationAssistant = Depends(get_arbitration_assistant),
) -> ArbitrationResponse:
    try:
        result = invoke(lambda: explain_week(uow, week_start, payload.task_ids, assistant))
    except ArbitrationNotConfigured as exc:
        raise HTTPException(status_code=503, detail="OpenAI assistance is not configured") from exc
    except ArbitrationUnavailable as exc:
        raise HTTPException(status_code=502, detail="AI arbitration is unavailable") from exc
    return ArbitrationResponse(
        proposal=ProposalResponse.from_domain(result.proposal),
        explanations=list(result.explanations),
    )
