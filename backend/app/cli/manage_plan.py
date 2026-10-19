"""
CipherQ Administrative CLI: Subscription Plan Management
Direct command-line tool for administrative tier upgrades and downgrades.
Usage:
    python -m backend.app.cli.manage_plan <email> <FREE|PRIVATE_VAULT|VAULT_AI> [--reason REASON]
"""
import asyncio
import sys
import argparse
from pathlib import Path

# Ensure backend package is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from sqlalchemy.future import select
from backend.app.db.session import AsyncSessionLocal
from backend.app.db.models import User, PlanAuditEvent
from backend.app.services.entitlements import entitlement_service


async def set_user_plan(email: str, new_plan: str, reason: str = "cli_admin_action") -> int:
    target_plan = new_plan.strip().upper()
    if target_plan not in ("FREE", "PRIVATE_VAULT", "VAULT_AI", "PREMIUM", "CREATOR"):
        print(f"Error: Invalid plan '{new_plan}'.")
        return 1

    async with AsyncSessionLocal() as db:
        stmt = select(User).where(User.email == email.strip().lower())
        user = (await db.execute(stmt)).scalar_one_or_none()

        if not user:
            print(f"Error: User with email '{email}' not found.")
            return 1

        old_plan = user.plan_type
        if old_plan == target_plan:
            print(f"Notice: User '{email}' is already on plan {target_plan}.")
            return 0

        # Create audit entry
        audit_event = PlanAuditEvent(
            user_id=user.id,
            old_plan=old_plan,
            new_plan=target_plan,
            changed_by="cli_admin",
            reason=reason
        )
        db.add(audit_event)

        user.plan_type = target_plan
        await db.commit()
        await db.refresh(user)

        new_quota = entitlement_service.get_user_quota(user)
        print("=" * 60)
        print(f"CipherQ Plan Update Successful:")
        print(f"  User:         {user.email} (ID: {user.id})")
        print(f"  Previous:     {old_plan}")
        print(f"  New Plan:     {user.plan_type}")
        print(f"  Quota:        {new_quota} bytes ({new_quota // 1_000_000_000} GB)")
        print(f"  Audit Record: Saved (Reason: {reason})")
        print("=" * 60)
        return 0


def main():
    parser = argparse.ArgumentParser(description="CipherQ Subscription Plan Management CLI")
    parser.add_argument("email", help="User email address")
    parser.add_argument(
        "plan",
        choices=[
            "FREE", "PRIVATE_VAULT", "VAULT_AI", "PREMIUM", "CREATOR",
            "free", "private_vault", "vault_ai", "premium", "creator",
        ],
        help="Target plan tier",
    )
    parser.add_argument("--reason", default="cli_admin_action", help="Audit reason for plan modification")

    args = parser.parse_args()
    exit_code = asyncio.run(set_user_plan(args.email, args.plan, args.reason))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
