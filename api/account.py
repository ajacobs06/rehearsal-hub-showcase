"""A member's own data: download everything (UK GDPR access) or delete the account (erasure)."""

from fastapi import APIRouter, Depends, HTTPException

from auth import current_member, now
from models import Member
from store import DocStore, get_feedback_store, get_progress_store, get_rehearsal_store, get_store

router = APIRouter(prefix="/api/me")


@router.get("/export")
def export_my_data(
    me: Member = Depends(current_member),
    progress: DocStore = Depends(get_progress_store),
    rehearsals: DocStore = Depends(get_rehearsal_store),
    feedback: DocStore = Depends(get_feedback_store),
) -> dict:
    return {
        "exportedAt": now(),
        "member": me.model_dump(),
        "progress": progress.find("memberId", me.id),
        "rsvps": [
            {"rehearsalId": r["id"], "start": r["start"], "venue": r["venue"], **r["rsvps"][me.id]}
            for r in rehearsals.list_all()
            if me.id in r.get("rsvps", {})
        ],
        "feedback": feedback.find("memberId", me.id),
    }


@router.delete("", status_code=204)
def delete_my_account(
    me: Member = Depends(current_member),
    members: DocStore = Depends(get_store),
    progress: DocStore = Depends(get_progress_store),
    rehearsals: DocStore = Depends(get_rehearsal_store),
    feedback: DocStore = Depends(get_feedback_store),
) -> None:
    # The site must always have an owner: hand ownership over first.
    if me.role == "owner":
        raise HTTPException(400, detail={"reason": "owner_must_hand_over"})
    for d in progress.find("memberId", me.id):
        progress.delete(d["id"], partition=d["songId"])
    for r in rehearsals.list_all():
        if me.id in r.get("rsvps", {}):
            rehearsals.patch(r["id"], remove_fields=[("rsvps", me.id)])
    for d in feedback.find("memberId", me.id):
        feedback.delete(d["id"])
    members.delete(me.id)
