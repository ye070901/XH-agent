"""前置测试采集 API。"""

from fastapi import APIRouter, HTTPException

from ..evaluation.pretest import public_question_bank, score_pretest
from ..schemas import PretestScoreResponse, PretestSubmission

router = APIRouter(prefix="/api/pretests", tags=["pretests"])


@router.get("/questions")
async def get_pretest_questions() -> dict:
    return public_question_bank()


@router.post("/score", response_model=PretestScoreResponse)
async def submit_pretest(payload: PretestSubmission) -> dict:
    try:
        return score_pretest(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
