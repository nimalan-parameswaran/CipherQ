"""
CipherQ Administrative and Plan Entitlement Management API
Controlled administrative operations for subscription tier modifications and audit logging.
Strictly protected via X-Admin-Token; unauthorized users are rejected with 403 Forbidden.
"""
from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel, Field
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.db.session import get_db
from backend.app.db.models import User, PlanAuditEvent
from backend.app.services.entitlements import entitlement_service

router = APIRouter(prefix="/admin", tags=["Admin"])


def verify_admin_token(x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token")) -> str:
    """
    Validates that the administrative token is provided and matches server configuration.
    Ordinary user session cookies grant zero administrative access.
    """
    if not x_admin_token or x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized administrative operation. Invalid or missing X-Admin-Token header."
        )
    return x_admin_token


class PlanChangeRequest(BaseModel):
    user_id: Optional[str] = Field(None, description="UUID of target user")
    email: Optional[str] = Field(None, description="Email address of target user")
    new_plan: str = Field(..., pattern="^(FREE|PREMIUM|CREATOR)$", description="Target plan: FREE, PREMIUM, or CREATOR")
    reason: Optional[str] = Field(default="admin_modification", max_length=255)


class PlanChangeResponse(BaseModel):
    user_id: str
    email: str
    old_plan: str
    new_plan: str
    storage_quota_bytes: int
    message: str


class AuditLogResponse(BaseModel):
    id: str
    user_id: str
    old_plan: str
    new_plan: str
    changed_by: str
    reason: Optional[str]
    created_at: datetime


@router.post("/users/plan", response_model=PlanChangeResponse)
async def change_user_plan(
    payload: PlanChangeRequest,
    _admin_auth: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db)
):
    """
    Administratively modify a user's subscription tier (FREE <-> PREMIUM).
    - On upgrade: applies higher quota and semantic capabilities immediately.
    - On downgrade: preserves existing files even if over quota; blocks new uploads until below limit.
    - Records an immutable audit log entry.
    """
    if not payload.user_id and not payload.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either user_id or email must be provided to locate the user."
        )

    # Locate user
    if payload.user_id:
        stmt = select(User).where(User.id == payload.user_id)
    else:
        stmt = select(User).where(User.email == payload.email)

    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target user not found."
        )

    old_plan = user.plan_type
    target_plan = payload.new_plan.upper()

    # Record auditable plan modification event
    audit_entry = PlanAuditEvent(
        user_id=user.id,
        old_plan=old_plan,
        new_plan=target_plan,
        changed_by="admin_api",
        reason=payload.reason or "administrative_modification"
    )
    db.add(audit_entry)

    # Update authoritative plan
    user.plan_type = target_plan
    await db.commit()
    await db.refresh(user)

    new_quota = entitlement_service.get_user_quota(user)

    return PlanChangeResponse(
        user_id=user.id,
        email=user.email,
        old_plan=old_plan,
        new_plan=user.plan_type,
        storage_quota_bytes=new_quota,
        message=f"Successfully transitioned user {user.email} from {old_plan} to {user.plan_type}."
    )


@router.get("/audit-logs", response_model=List[AuditLogResponse])
async def list_plan_audit_logs(
    user_id: Optional[str] = None,
    limit: int = 50,
    _admin_auth: str = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db)
):
    """
    Return recent auditable plan change events.
    Strictly excludes passwords, session tokens, or file contents.
    """
    stmt = select(PlanAuditEvent).order_by(PlanAuditEvent.created_at.desc()).limit(min(limit, 100))
    if user_id:
        stmt = stmt.where(PlanAuditEvent.user_id == user_id)

    results = (await db.execute(stmt)).scalars().all()
    return [
        AuditLogResponse(
            id=a.id,
            user_id=a.user_id,
            old_plan=a.old_plan,
            new_plan=a.new_plan,
            changed_by=a.changed_by,
            reason=a.reason,
            created_at=a.created_at
        )
        for a in results
    ]
