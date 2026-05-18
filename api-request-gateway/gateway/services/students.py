from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db.models import Platform, Student
from db.session import session_scope

logger = logging.getLogger(__name__)


async def get_or_create_student(platform: Platform, external_student_id: str) -> uuid.UUID:
    for attempt in range(3):
        try:
            async with session_scope() as session:
                row = (
                    await session.execute(
                        select(Student).where(
                            Student.external_id == external_student_id,
                            Student.platform_id == platform.id,
                        )
                    )
                ).scalar_one_or_none()
                if row is not None:
                    return row.id
                st = Student(
                    external_id=external_student_id,
                    platform=platform.name,
                    platform_id=platform.id,
                )
                session.add(st)
                await session.flush()
                return st.id
        except IntegrityError:
            logger.debug("Student insert raced (attempt %s), retrying", attempt + 1)
            if attempt == 2:
                raise
            continue
    raise RuntimeError("Unable to resolve student row")
