"""Phase 08 — attempt result + review screens.

GET /attempts/{id}/result                  score + topic breakdown + recommendations
GET /attempts/{id}/review                  paginated review of all questions
GET /attempts/{id}/review/q/{order}        single-question review
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.auth.csrf import CSRF_FORM_FIELD, issue_csrf_token
from app.auth.permissions import AttemptOwnerDep
from app.deps import SessionDep
from app.models.attempts import AttemptAnswer
from app.models.catalog import Exam
from app.models.questions import Question, QuestionExplanation, QuestionOption
from app.paths import TEMPLATES_DIR
from app.services import scoring_service

router = APIRouter(prefix="/attempts", tags=["attempts"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/{attempt_id}/result", response_class=HTMLResponse)
def result(
    request: Request,
    attempt_id: int,
    owner: AttemptOwnerDep,
    session: SessionDep,
) -> HTMLResponse:
    attempt = owner.attempt
    if attempt.finished_at is None:
        # Result page only for finished attempts.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="attempt not finished")
    breakdown = scoring_service.topic_breakdown(session, attempt_id=attempt_id)
    recs = scoring_service.weak_topic_recommendations(
        breakdown, overall_percent=float(attempt.score_percent or 0)
    )
    exam = session.get(Exam, attempt.exam_id)
    return templates.TemplateResponse(
        request,
        "attempts/result.html",
        {
            "current_user": owner.user,
            "is_guest": owner.is_guest,
            "attempt": attempt,
            "exam": exam,
            "breakdown": breakdown,
            "recommendations": recs,
        },
    )


_REVIEW_FILTERS = {"all", "wrong", "flagged"}


@router.get("/{attempt_id}/review", response_class=HTMLResponse)
def review_list(
    request: Request,
    attempt_id: int,
    owner: AttemptOwnerDep,
    session: SessionDep,
) -> HTMLResponse:
    attempt = owner.attempt
    if attempt.finished_at is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="attempt not finished")

    f = request.query_params.get("filter", "all").lower()
    wrong_only = request.query_params.get("wrong_only") == "1" or f == "wrong"
    flagged_only = f == "flagged"

    stmt = (
        select(AttemptAnswer, Question)
        .join(Question, Question.id == AttemptAnswer.question_id)
        .where(AttemptAnswer.attempt_id == attempt_id)
    )
    if wrong_only:
        stmt = stmt.where(AttemptAnswer.is_correct.is_(False))
    if flagged_only:
        stmt = stmt.where(AttemptAnswer.flagged.is_(True))
    stmt = stmt.order_by(AttemptAnswer.order_index)
    rows = session.execute(stmt).all()
    return templates.TemplateResponse(
        request,
        "attempts/review_list.html",
        {
            "current_user": owner.user,
            "is_guest": owner.is_guest,
            "attempt": attempt,
            "rows": rows,
            "filter": f if f in _REVIEW_FILTERS else "all",
        },
    )


@router.get("/{attempt_id}/review/q/{order}", response_class=HTMLResponse)
def review_question(
    request: Request,
    attempt_id: int,
    order: int,
    owner: AttemptOwnerDep,
    session: SessionDep,
) -> HTMLResponse:
    attempt = owner.attempt
    if attempt.finished_at is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="attempt not finished")

    answer = session.scalars(
        select(AttemptAnswer)
        .where(AttemptAnswer.attempt_id == attempt_id)
        .where(AttemptAnswer.order_index == order)
    ).first()
    if answer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    question = session.get(Question, answer.question_id)
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    options = list(
        session.scalars(
            select(QuestionOption)
            .where(QuestionOption.question_id == question.id)
            .order_by(QuestionOption.order_index)
        )
    )
    explanation = session.scalars(
        select(QuestionExplanation).where(QuestionExplanation.question_id == question.id)
    ).first()
    selected_set = {
        p.strip().upper() for p in (answer.selected_options or "").split(",") if p.strip()
    }
    correct_set = {o.label for o in options if o.is_correct and o.label}

    total = (
        session.scalar(
            select(func.count(AttemptAnswer.id)).where(AttemptAnswer.attempt_id == attempt_id)
        )
        or 0
    )

    placeholder = HTMLResponse(content="")
    csrf = issue_csrf_token(placeholder)
    rendered = templates.TemplateResponse(
        request,
        "attempts/review_question.html",
        {
            "current_user": owner.user,
            "is_guest": owner.is_guest,
            "attempt": attempt,
            "answer": answer,
            "question": question,
            "options": options,
            "explanation": explanation,
            "selected_set": selected_set,
            "correct_set": correct_set,
            "total": int(total),
            CSRF_FORM_FIELD: csrf,
        },
    )
    for k, v in placeholder.raw_headers:
        if k == b"set-cookie":
            rendered.raw_headers.append((k, v))
    return rendered
