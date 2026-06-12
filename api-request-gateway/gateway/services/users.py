from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from db.models import Platform, Student, User
from db.session import session_scope
from gateway.services.auth import create_access_token

logger = logging.getLogger(__name__)


async def register_user(platform: Platform) -> tuple[User, str]:
    user_id = uuid.uuid4()
    async with session_scope() as session:
        user = User(id=user_id, platform_id=platform.id)
        student = Student(
            id=user_id,
            external_id=str(user_id),
            platform=platform.name,
            platform_id=platform.id,
        )
        session.add(user)
        session.add(student)
        await session.flush()
    token = create_access_token(user_id=user_id, platform_id=platform.id)
    return user, token


async def get_user_for_platform(user_id: uuid.UUID, platform_id: uuid.UUID) -> User | None:
    async with session_scope() as session:
        return (
            await session.execute(
                select(User).where(
                    User.id == user_id,
                    User.platform_id == platform_id,
                )
            )
        ).scalar_one_or_none()


async def issue_token_for_user(user: User) -> str:
    return create_access_token(user_id=user.id, platform_id=user.platform_id)
