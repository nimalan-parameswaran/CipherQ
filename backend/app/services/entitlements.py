"""
CipherQ Entitlements and Quota Management Service
Authoritative backend definition and enforcement of user storage quotas,
plan capabilities, and concurrency-safe in-flight quota reservations.
"""
import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from backend.app.core.config import settings
from backend.app.db.models import User


class QuotaExceededError(Exception):
    """Raised when an operation would exceed the user's allocated storage quota."""
    def __init__(self, message: str, current_bytes: int = 0, quota_bytes: int = 0):
        super().__init__(message)
        self.current_bytes = current_bytes
        self.quota_bytes = quota_bytes


class PlanPermissionError(Exception):
    """Raised when an operation is disallowed by the user's current subscription tier."""
    pass


class InFlightQuotaTracker:
    """
    Thread- and async-safe tracker for in-flight streaming uploads.
    Ensures that concurrent uploads racing for the same user's quota
    cannot jointly exceed the storage limit.
    """

    def __init__(self):
        self._in_flight_bytes: Dict[str, int] = defaultdict(int)
        self._user_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._global_lock = asyncio.Lock()

    async def _get_user_lock(self, user_id: str) -> asyncio.Lock:
        async with self._global_lock:
            return self._user_locks[user_id]

    def get_in_flight_bytes(self, user_id: str) -> int:
        return self._in_flight_bytes.get(user_id, 0)

    @asynccontextmanager
    async def track_upload(
        self,
        user_id: str,
        current_committed_bytes: int,
        quota_bytes: int,
        content_length: Optional[int] = None
    ):
        """
        Context manager that tracks in-flight upload bytes and ensures safe release on completion or error.
        If Content-Length is provided, checks upfront before streaming.
        """
        user_lock = await self._get_user_lock(user_id)
        allocated_in_flight = 0

        async with user_lock:
            active_in_flight = self._in_flight_bytes[user_id]
            total_projected = current_committed_bytes + active_in_flight

            # 1. Hard check: already at or over quota
            if total_projected >= quota_bytes:
                raise QuotaExceededError(
                    f"Storage quota exceeded. Your current usage ({current_committed_bytes} bytes) "
                    f"plus in-progress uploads ({active_in_flight} bytes) meets or exceeds your plan limit ({quota_bytes} bytes).",
                    current_bytes=total_projected,
                    quota_bytes=quota_bytes
                )

            # 2. Check Content-Length if declared by client
            if content_length is not None and content_length > 0:
                if total_projected + content_length > quota_bytes:
                    raise QuotaExceededError(
                        f"File size ({content_length} bytes) would exceed your remaining storage quota "
                        f"({quota_bytes - total_projected} bytes remaining of {quota_bytes} bytes limit).",
                        current_bytes=total_projected + content_length,
                        quota_bytes=quota_bytes
                    )
                # Pre-allocate declared length to guard against concurrent requests
                self._in_flight_bytes[user_id] += content_length
                allocated_in_flight = content_length

        class StreamTracker:
            def __init__(self, outer, u_id, c_committed, q_limit, initial_alloc):
                self.outer = outer
                self.user_id = u_id
                self.current_committed = c_committed
                self.quota_limit = q_limit
                self.total_streamed_bytes = 0
                self.pre_allocated = initial_alloc

            async def add_streamed_chunk(self, chunk_len: int):
                self.total_streamed_bytes += chunk_len
                # If streamed bytes exceed any upfront pre-allocation, record the excess
                if self.total_streamed_bytes > self.pre_allocated:
                    excess = self.total_streamed_bytes - self.pre_allocated
                    lock = await self.outer._get_user_lock(self.user_id)
                    async with lock:
                        current_total = self.current_committed + self.outer._in_flight_bytes[self.user_id] + excess
                        if current_total > self.quota_limit:
                            raise QuotaExceededError(
                                f"Streaming upload exceeded remaining quota ({self.quota_limit} bytes cap).",
                                current_bytes=current_total,
                                quota_bytes=self.quota_limit
                            )
                        self.outer._in_flight_bytes[self.user_id] += excess
                        self.pre_allocated = self.total_streamed_bytes

        tracker = StreamTracker(self, user_id, current_committed_bytes, quota_bytes, allocated_in_flight)

        try:
            yield tracker
        finally:
            # Always clean up tracked in-flight reservation
            user_lock = await self._get_user_lock(user_id)
            async with user_lock:
                current_val = self._in_flight_bytes.get(user_id, 0)
                amount_to_release = tracker.pre_allocated
                self._in_flight_bytes[user_id] = max(0, current_val - amount_to_release)
                if self._in_flight_bytes[user_id] == 0:
                    self._in_flight_bytes.pop(user_id, None)


class EntitlementService:
    """Authoritative service defining plan capabilities and quotas."""

    def __init__(self):
        self.tracker = InFlightQuotaTracker()

    def get_plan_quota(self, plan_type: str) -> int:
        """
        Returns maximum allowed storage in decimal bytes.
        - FREE: 1 GB (1,000,000,000 bytes)
        - PREMIUM: 5 GB (5,000,000,000 bytes)
        """
        if plan_type.upper() == "PREMIUM":
            return settings.PREMIUM_QUOTA_BYTES
        return settings.FREE_QUOTA_BYTES

    def get_user_quota(self, user: User) -> int:
        return self.get_plan_quota(user.plan_type)

    def get_user_entitlements(self, user: User) -> Dict[str, Any]:
        """Returns structured entitlement dictionary for the user."""
        is_premium = (user.plan_type.upper() == "PREMIUM")
        quota = self.get_user_quota(user)
        return {
            "plan_type": user.plan_type,
            "storage_quota_bytes": quota,
            "has_semantic_search": is_premium,
            "has_ai_citations": True,
            "ai_daily_limit": 100 if is_premium else 0,
            "is_generative_llm_active": False  # Dual-tier rule: false unless validated & loaded
        }

    def validate_plan_access(self, user: User, feature: str) -> None:
        """Enforces tier-specific feature restrictions."""
        if feature == "SEMANTIC_SEARCH" and user.plan_type.upper() != "PREMIUM":
            raise PlanPermissionError(
                "Semantic vector search and local embeddings require an active PREMIUM subscription."
            )


entitlement_service = EntitlementService()
