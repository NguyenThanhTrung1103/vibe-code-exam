"""Public Learn Mode — study published questions at the learner's pace.

GET /learn/{exam_slug}            paginated study page (5 questions / page)

No login, no timer, no scoring. Each question carries a per-question
"Show Answer" toggle that uses the same `?reveal=` query-string pattern as
the practice attempt page so refreshing or sharing the URL preserves which
answers are revealed.

`exam_slug` is unique per (course_id, slug); when two courses happen to share
the same slug we pick the most-recently updated published one. Homelab — we
prefer a working URL over a 409.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.deps import SessionDep
from app.models.catalog import Course, Exam, Provider
from app.models.enums import QuestionStatus
from app.models.questions import Question, QuestionExplanation, QuestionOption
from app.paths import TEMPLATES_DIR
from app.routers.public.catalog_query import published_exam_filter

router = APIRouter(prefix="/learn", tags=["public", "learn"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

PAGE_SIZE = 5


def _parse_reveal(raw: str | None, page_start: int, page_end: int) -> set[int]:
    """Parse `?reveal=2,4,7` → set of ints clamped to current page range."""
    if not raw:
        return set()
    out: set[int] = set()
    for chunk in raw.split(","):
        token = chunk.strip()
        if not token.isdigit():
            continue
        n = int(token)
        if page_start <= n <= page_end:
            out.add(n)
    return out


@router.get("/{exam_slug}", response_class=HTMLResponse)
def learn_page(
    request: Request,
    exam_slug: str,
    session: SessionDep,
) -> HTMLResponse:
    row = session.execute(
        select(Exam, Course, Provider)
        .join(Course, Exam.course_id == Course.id)
        .join(Provider, Course.provider_id == Provider.id)
        .where(Exam.slug == exam_slug)
        .where(published_exam_filter())
        .order_by(Exam.updated_at.desc())
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="exam not found")
    exam, course, provider = row

    total = (
        session.scalar(
            select(func.count(Question.id))
            .where(Question.exam_id == exam.id)
            .where(Question.status == QuestionStatus.published)
            .where(Question.deleted_at.is_(None))
            .where(Question.retired_at.is_(None))
        )
        or 0
    )
    total = int(total)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE) if total else 1

    try:
        page_num = int(request.query_params.get("page", "1") or 1)
    except ValueError:
        page_num = 1
    page_num = max(1, min(page_num, total_pages))

    page_start = (page_num - 1) * PAGE_SIZE + 1 if total else 0
    page_end = min(page_start + PAGE_SIZE - 1, total) if total else 0

    raw_reveal = request.query_params.get("reveal") or ""
    reveal_set = _parse_reveal(raw_reveal, page_start, page_end)

    cards: list[dict] = []
    if total > 0:
        questions = list(
            session.scalars(
                select(Question)
                .where(Question.exam_id == exam.id)
                .where(Question.status == QuestionStatus.published)
                .where(Question.deleted_at.is_(None))
                .where(Question.retired_at.is_(None))
                .order_by(Question.id)
                .offset((page_num - 1) * PAGE_SIZE)
                .limit(PAGE_SIZE)
            )
        )
        qids = [q.id for q in questions]
        options_by_qid: dict[int, list[QuestionOption]] = {}
        if qids:
            for opt in session.scalars(
                select(QuestionOption)
                .where(QuestionOption.question_id.in_(qids))
                .order_by(QuestionOption.question_id, QuestionOption.order_index)
            ):
                options_by_qid.setdefault(opt.question_id, []).append(opt)
        explanations_by_qid: dict[int, str | None] = {}
        if qids:
            for ex in session.scalars(
                select(QuestionExplanation).where(QuestionExplanation.question_id.in_(qids))
            ):
                explanations_by_qid[ex.question_id] = (
                    ex.overall_explanation or ex.correct_explanation
                )

        for offset, q in enumerate(questions):
            position = page_start + offset
            is_revealed = position in reveal_set
            new_set = (
                reveal_set - {position} if is_revealed else reveal_set | {position}
            )
            toggle_param = ",".join(str(p) for p in sorted(new_set))
            qs = f"page={page_num}"
            if toggle_param:
                qs += f"&reveal={toggle_param}"
            toggle_url = f"?{qs}#q{position}"
            cards.append(
                {
                    "question": q,
                    "options": options_by_qid.get(q.id, []),
                    "explanation": explanations_by_qid.get(q.id),
                    "position": position,
                    "revealed": is_revealed,
                    "toggle_url": toggle_url,
                }
            )

    page_query = f"&reveal={raw_reveal}" if raw_reveal else ""
    prev_url = f"?page={page_num - 1}{page_query}" if page_num > 1 else None
    next_url = f"?page={page_num + 1}{page_query}" if page_num < total_pages else None

    return templates.TemplateResponse(
        request,
        "public/learn.html",
        {
            "exam": exam,
            "course": course,
            "provider": provider,
            "cards": cards,
            "page_num": page_num,
            "total_pages": total_pages,
            "page_start": page_start,
            "page_end": page_end,
            "total_questions": total,
            "prev_url": prev_url,
            "next_url": next_url,
        },
    )


__all__ = ["router"]
