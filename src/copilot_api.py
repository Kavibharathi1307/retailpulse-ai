"""Copilot API endpoints (Milestone 4).

POST /api/copilot/query accepts a natural-language retail question, runs it
through the grounded copilot service, and returns the natural-language answer
together with the deterministic evidence it was grounded on.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.gemini.errors import CopilotValidationError
from src.gemini.service import MAX_QUESTION_LENGTH, CopilotService

router = APIRouter(prefix="/api/copilot", tags=["copilot"])

# Single shared instance so HTTP tests can swap in a fake client.
copilot_service = CopilotService()


class CopilotQuery(BaseModel):
    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_LENGTH)


@router.post("/query")
def copilot_query(payload: CopilotQuery) -> dict:
    try:
        return copilot_service.answer(payload.question)
    except CopilotValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_question", "message": str(exc)},
        ) from exc