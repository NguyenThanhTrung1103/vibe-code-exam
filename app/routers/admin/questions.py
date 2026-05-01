"""Admin question-bank routes (Phase 06).

GET   /admin/questions                    list with filters
GET   /admin/questions/new                manual create form
POST  /admin/questions                    create
GET   /admin/questions/{id}/edit          editor
POST  /admin/questions/{id}/edit          save text/type/topic/difficulty
POST  /admin/questions/{id}/options       replace options + correct answer
POST  /admin/questions/{id}/explanation   set overall explanation
POST  /admin/questions/{id}/retire        soft-retire with reason
POST  /admin/questions/{id}/restore       un-retire
POST  /admin/questions/bulk-topic         assign topic to many
"""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy import select

from app.auth.permissions import RequireAdmin
from app.deps import SessionDep
from app.middleware import REQUEST_ID_HEADER
from app.models.catalog import Course, Exam, Provider, Topic
from app.models.enums import QuestionDifficulty, QuestionStatus, QuestionType
from app.models.questions import Question, QuestionExplanation, QuestionOption
from app.routers.admin._common import (
    flash_error,
    render_with_csrf,
    require_csrf,
    templates,
)
from app.schemas.question import (
    ExplanationIn,
    OptionsReplace,
    QuestionCreate,
    QuestionUpdate,
    RetireIn,
)
from app.services import question_service

router = APIRouter(prefix="/admin/questions", tags=["admin", "questions"])


# ---------------------------------------------------------------------------
# List + filters
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def list_questions(request: Request, user: RequireAdmin, session: SessionDep) -> HTMLResponse:
    qp = request.query_params
    exam_id = _opt_int(qp.get("exam_id"))
    topic_id = _opt_int(qp.get("topic_id"))
    status_filter = qp.get("status")
    difficulty_filter = qp.get("difficulty")
    text_q = qp.get("q") or ""
    page = int(qp.get("page") or 1)
    page_size = 50

    stmt = (
        select(Question, Exam, Provider)
        .join(Exam, Question.exam_id == Exam.id)
        .join(Course, Exam.course_id == Course.id)
        .join(Provider, Course.provider_id == Provider.id)
        .where(Question.deleted_at.is_(None))
    )
    if exam_id:
        stmt = stmt.where(Question.exam_id == exam_id)
    if topic_id:
        stmt = stmt.where(Question.topic_id == topic_id)
    if status_filter and status_filter != "all":
        with contextlib.suppress(ValueError):
            stmt = stmt.where(Question.status == QuestionStatus(status_filter))
    if difficulty_filter and difficulty_filter != "all":
        with contextlib.suppress(ValueError):
            stmt = stmt.where(Question.difficulty == QuestionDifficulty(difficulty_filter))
    if text_q:
        stmt = stmt.where(Question.question_text.ilike(f"%{text_q}%"))
    stmt = stmt.order_by(Question.id.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = session.execute(stmt).all()

    exams = session.scalars(select(Exam).where(Exam.deleted_at.is_(None)).order_by(Exam.name)).all()
    return render_with_csrf(
        request,
        "admin/questions/list.html",
        {
            "current_user": user,
            "rows": rows,
            "exams": exams,
            "page": page,
            "filters": {
                "exam_id": exam_id or "",
                "topic_id": topic_id or "",
                "status": status_filter or "",
                "difficulty": difficulty_filter or "",
                "q": text_q,
            },
        },
    )


# ---------------------------------------------------------------------------
# New / create
# ---------------------------------------------------------------------------


@router.get("/new", response_class=HTMLResponse)
def new_form(request: Request, user: RequireAdmin, session: SessionDep) -> HTMLResponse:
    exams = session.scalars(select(Exam).where(Exam.deleted_at.is_(None)).order_by(Exam.name)).all()
    topics = session.scalars(select(Topic).order_by(Topic.name)).all()
    return render_with_csrf(
        request,
        "admin/questions/new.html",
        {"current_user": user, "exams": exams, "topics": topics},
    )


@router.post("", response_class=HTMLResponse)
async def create(
    request: Request,
    user: RequireAdmin,
    session: SessionDep,
) -> HTMLResponse:
    form = await request.form()
    require_csrf(request, str(form.get("csrf_token", "")))
    payload_dict = _build_create_payload(form)
    try:
        payload = QuestionCreate.model_validate(payload_dict)
    except ValidationError as exc:
        return flash_error(request, str(exc.errors()[0]["msg"]))
    try:
        q = question_service.create_question(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            **payload.to_service_kwargs(),
        )
    except question_service.QuestionValidationError as exc:
        return flash_error(request, str(exc))
    session.commit()
    response = HTMLResponse(content="", status_code=200)
    response.headers["HX-Redirect"] = f"/admin/questions/{q.id}/edit"
    response.headers["Location"] = f"/admin/questions/{q.id}/edit"
    return response


# ---------------------------------------------------------------------------
# Edit (render)
# ---------------------------------------------------------------------------


@router.get("/{question_id}/edit", response_class=HTMLResponse)
def edit_form(
    request: Request,
    question_id: int,
    user: RequireAdmin,
    session: SessionDep,
) -> HTMLResponse:
    q = session.get(Question, question_id)
    if q is None or q.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    options = list(
        session.scalars(
            select(QuestionOption)
            .where(QuestionOption.question_id == q.id)
            .order_by(QuestionOption.order_index)
        )
    )
    explanation = session.scalars(
        select(QuestionExplanation).where(QuestionExplanation.question_id == q.id)
    ).first()
    topics = session.scalars(
        select(Topic).where(Topic.exam_id == q.exam_id).order_by(Topic.name)
    ).all()
    exam = session.get(Exam, q.exam_id)
    return render_with_csrf(
        request,
        "admin/questions/edit.html",
        {
            "current_user": user,
            "q": q,
            "options": options,
            "explanation": explanation,
            "topics": topics,
            "exam": exam,
        },
    )


# ---------------------------------------------------------------------------
# Edit (save text/type/topic/difficulty/status)
# ---------------------------------------------------------------------------


@router.post("/{question_id}/edit", response_class=HTMLResponse)
async def save_edit(
    request: Request,
    question_id: int,
    user: RequireAdmin,
    session: SessionDep,
) -> HTMLResponse:
    form = await request.form()
    require_csrf(request, str(form.get("csrf_token", "")))
    try:
        payload = QuestionUpdate.model_validate(
            {
                "question_text": form.get("question_text") or None,
                "question_type": form.get("question_type") or None,
                "difficulty": form.get("difficulty") or None,
                "topic_id": _opt_int(form.get("topic_id")),
                "status": form.get("status") or None,
            }
        )
    except ValidationError as exc:
        return flash_error(request, str(exc.errors()[0]["msg"]))
    try:
        question_service.update_question(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            question_id=question_id,
            question_text=payload.question_text,
            question_type=(QuestionType(payload.question_type) if payload.question_type else None),
            difficulty=(QuestionDifficulty(payload.difficulty) if payload.difficulty else None),
            topic_id=payload.topic_id,
            status=(QuestionStatus(payload.status) if payload.status else None),
        )
    except question_service.QuestionValidationError as exc:
        return flash_error(request, str(exc))
    except question_service.QuestionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    session.commit()
    response = HTMLResponse(content="", status_code=200)
    response.headers["HX-Redirect"] = f"/admin/questions/{question_id}/edit"
    response.headers["Location"] = f"/admin/questions/{question_id}/edit"
    return response


# ---------------------------------------------------------------------------
# Options replace
# ---------------------------------------------------------------------------


@router.post("/{question_id}/options", response_class=HTMLResponse)
async def replace_options(
    request: Request,
    question_id: int,
    user: RequireAdmin,
    session: SessionDep,
) -> HTMLResponse:
    form = await request.form()
    require_csrf(request, str(form.get("csrf_token", "")))
    payload_dict = _build_options_payload(form)
    try:
        payload = OptionsReplace.model_validate(payload_dict)
    except ValidationError as exc:
        return flash_error(request, str(exc.errors()[0]["msg"]))
    try:
        question_service.set_options(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            question_id=question_id,
            options=[(o.label.upper(), o.text) for o in payload.options],
            correct_answer=[c.upper() for c in payload.correct_answer],
        )
    except question_service.QuestionValidationError as exc:
        return flash_error(request, str(exc))
    except question_service.QuestionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    session.commit()
    response = HTMLResponse(content="", status_code=200)
    response.headers["HX-Redirect"] = f"/admin/questions/{question_id}/edit"
    response.headers["Location"] = f"/admin/questions/{question_id}/edit"
    return response


# ---------------------------------------------------------------------------
# Explanation
# ---------------------------------------------------------------------------


@router.post("/{question_id}/explanation", response_class=HTMLResponse)
def save_explanation(
    request: Request,
    question_id: int,
    user: RequireAdmin,
    session: SessionDep,
    text: str = Form(""),
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        payload = ExplanationIn.model_validate({"text": text})
    except ValidationError as exc:
        return flash_error(request, str(exc.errors()[0]["msg"]))
    try:
        question_service.set_overall_explanation(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            question_id=question_id,
            text=payload.text,
        )
    except question_service.QuestionValidationError as exc:
        return flash_error(request, str(exc))
    except question_service.QuestionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    session.commit()
    response = HTMLResponse(content="", status_code=200)
    response.headers["HX-Redirect"] = f"/admin/questions/{question_id}/edit"
    response.headers["Location"] = f"/admin/questions/{question_id}/edit"
    return response


# ---------------------------------------------------------------------------
# Retire / restore
# ---------------------------------------------------------------------------


@router.post("/{question_id}/retire", response_class=HTMLResponse)
def retire_question(
    request: Request,
    question_id: int,
    user: RequireAdmin,
    session: SessionDep,
    reason: str = Form(""),
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        payload = RetireIn.model_validate({"reason": reason})
    except ValidationError as exc:
        return flash_error(request, str(exc.errors()[0]["msg"]))
    try:
        question_service.retire(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            question_id=question_id,
            reason=payload.reason,
        )
    except question_service.QuestionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    session.commit()
    response = HTMLResponse(content="", status_code=200)
    response.headers["HX-Redirect"] = f"/admin/questions/{question_id}/edit"
    response.headers["Location"] = f"/admin/questions/{question_id}/edit"
    return response


@router.post("/{question_id}/restore", response_class=HTMLResponse)
def restore_question(
    request: Request,
    question_id: int,
    user: RequireAdmin,
    session: SessionDep,
    csrf_token: str = Form(""),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    try:
        question_service.restore(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            question_id=question_id,
        )
    except question_service.QuestionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    session.commit()
    response = HTMLResponse(content="", status_code=200)
    response.headers["HX-Redirect"] = f"/admin/questions/{question_id}/edit"
    response.headers["Location"] = f"/admin/questions/{question_id}/edit"
    return response


# ---------------------------------------------------------------------------
# Bulk topic assign
# ---------------------------------------------------------------------------


@router.post("/bulk-topic", response_class=HTMLResponse)
async def bulk_topic(
    request: Request,
    user: RequireAdmin,
    session: SessionDep,
) -> HTMLResponse:
    form = await request.form()
    require_csrf(request, str(form.get("csrf_token", "")))
    qids: list[int] = []
    for v in form.getlist("question_id"):
        if not isinstance(v, str):
            continue  # ignore UploadFile values
        try:
            qids.append(int(v))
        except (TypeError, ValueError):
            continue
    topic_id = _opt_int(form.get("topic_id"))
    try:
        n = question_service.assign_topic_bulk(
            session,
            actor=user,
            request_id=request.headers.get(REQUEST_ID_HEADER),
            question_ids=qids,
            topic_id=topic_id,
        )
    except question_service.QuestionValidationError as exc:
        return flash_error(request, str(exc))
    session.commit()
    return templates.TemplateResponse(request, "admin/questions/_bulk_result.html", {"count": n})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _opt_int(v) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _build_create_payload(form) -> dict:
    options = []
    for label in ("A", "B", "C", "D", "E"):
        text = (form.get(f"option_{label.lower()}") or "").strip()
        if text:
            options.append({"label": label, "text": text})
    correct_raw = form.get("correct_answer") or ""
    correct = [c.strip().upper() for c in str(correct_raw).split(",") if c.strip()]
    return {
        "exam_id": _opt_int(form.get("exam_id")) or 0,
        "question_text": form.get("question_text") or "",
        "question_type": form.get("question_type") or "single",
        "difficulty": form.get("difficulty") or None,
        "topic_id": _opt_int(form.get("topic_id")),
        "options": options,
        "correct_answer": correct,
        "overall_explanation": form.get("overall_explanation") or None,
    }


def _build_options_payload(form) -> dict:
    options = []
    for label in ("A", "B", "C", "D", "E"):
        text = (form.get(f"option_{label.lower()}") or "").strip()
        if text:
            options.append({"label": label, "text": text})
    correct_raw = form.get("correct_answer") or ""
    correct = [c.strip().upper() for c in str(correct_raw).split(",") if c.strip()]
    return {"options": options, "correct_answer": correct}
