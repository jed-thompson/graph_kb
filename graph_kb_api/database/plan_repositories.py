"""Async repository for plan_sessions table."""

from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from graph_kb_api.database.base import DatabaseError
from graph_kb_api.database.plan_models import PlanSession
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class PlanSessionRepository:
    """CRUD operations for plan_sessions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _execute(self, query):
        try:
            return await self.session.execute(query)
        except Exception as e:
            logger.error(f"Plan session query failed: {e}")
            raise DatabaseError(f"Database query failed: {e}", original=e) from e

    async def create(
        self,
        session_id: str,
        thread_id: str,
        user_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> PlanSession:
        """Insert a new plan session row."""
        now = datetime.now(UTC)
        row = PlanSession(
            id=session_id,
            thread_id=thread_id,
            user_id=user_id,
            name=name,
            description=description,
            workflow_status="running",
            current_phase="context",
            completed_phases={},
            fingerprints={},
            budget_state={},
            context_items={},
            created_at=now,
            updated_at=now,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(self, session_id: str) -> PlanSession | None:
        """Fetch a single plan session by primary key."""
        result = await self._execute(
            select(PlanSession).where(PlanSession.id == session_id),
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PlanSession]:
        """List sessions for a user, ordered by updated_at desc."""
        result = await self._execute(
            select(PlanSession)
            .where(PlanSession.user_id == user_id)
            .order_by(PlanSession.updated_at.desc())
            .limit(limit)
            .offset(offset),
        )
        return list(result.scalars().all())

    async def list_all(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PlanSession]:
        """List all sessions ordered by updated_at desc."""
        result = await self._execute(
            select(PlanSession)
            .order_by(PlanSession.updated_at.desc())
            .limit(limit)
            .offset(offset),
        )
        return list(result.scalars().all())

    async def update(
        self,
        session_id: str,
        **kwargs,
    ) -> PlanSession | None:
        """Update arbitrary columns on an existing session."""
        if not kwargs:
            return await self.get(session_id)
        kwargs["updated_at"] = datetime.now(UTC)
        await self._execute(
            update(PlanSession).where(PlanSession.id == session_id).values(**kwargs),
        )
        await self.session.flush()
        return await self.get(session_id)

    async def delete(self, session_id: str) -> bool:
        """Delete a session row. Returns True if a row was deleted."""
        result = await self._execute(
            delete(PlanSession).where(PlanSession.id == session_id),
        )
        await self.session.flush()
        return result.rowcount > 0
