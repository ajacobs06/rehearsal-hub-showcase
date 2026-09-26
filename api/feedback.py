import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from auth import current_member, now, require_role
from models import Feedback, FeedbackCreate, FeedbackUpdate, Member
from store import DocStore, get_feedback_store

router = APIRouter(prefix="/api/feedback")

DAILY_LIMIT = 20


@router.post("", status_code=201)
def send_feedback(
    body: FeedbackCreate,
    me: Member = Depends(current_member),
    store: DocStore = Depends(get_feedback_store),
) -> Feedback:
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    if sum(1 for d in store.find("memberId", me.id) if d["createdAt"] >= since) >= DAILY_LIMIT:
        raise HTTPException(429, detail={"reason": "too_much_feedback"})
    item = Feedback(
        id=uuid.uuid4().hex,
        memberId=me.id,
        name=me.name,
        email=me.email,
        message=body.message,
        page=body.page,
        createdAt=now(),
    )
    store.upsert(item.model_dump())
    return item


@router.get("")
def list_feedback(
    _: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_feedback_store),
) -> list[Feedback]:
    items = [Feedback(**d) for d in store.list_all()]
    # New before done; newest first within each (sorts are stable).
    items.sort(key=lambda f: f.createdAt, reverse=True)
    items.sort(key=lambda f: f.status == "done")
    return items


@router.patch("/{feedback_id}")
def update_feedback(
    feedback_id: str,
    body: FeedbackUpdate,
    _: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_feedback_store),
) -> Feedback:
    doc = store.get(feedback_id)
    if doc is None:
        raise HTTPException(404)
    item = Feedback(**{**doc, "status": body.status})
    store.upsert(item.model_dump())
    return item


@router.delete("/{feedback_id}", status_code=204)
def delete_feedback(
    feedback_id: str,
    _: Member = Depends(require_role("admin")),
    store: DocStore = Depends(get_feedback_store),
) -> None:
    if store.get(feedback_id) is None:
        raise HTTPException(404)
    store.delete(feedback_id)
