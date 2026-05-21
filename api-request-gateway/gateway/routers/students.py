from __future__ import annotations

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from db.models import Analysis, GeneratedTask, Platform, Student
from db.session import session_scope
from gateway.schemas.response import (
    StudentHistoryAnalysis,
    StudentHistoryGeneratedTask,
    StudentHistoryResponse,
    StudentProfileResponse,
)
from gateway.services.auth import check_rate_limit, verify_api_key
from gateway.services.student_profile import get_student_profile

router = APIRouter()


def get_redis(request: Request) -> redis.Redis:
    return request.app.state.redis


async def _resolve_student(platform: Platform, external_student_id: str) -> Student:
    async with session_scope() as session:
        student = (
            await session.execute(
                select(Student).where(
                    Student.external_id == external_student_id,
                    Student.platform_id == platform.id,
                )
            )
        ).scalar_one_or_none()
        if student is None:
            raise HTTPException(status_code=404, detail="Unknown student_id")
        return student


@router.get("/students/{student_id}/history", response_model=StudentHistoryResponse)
async def student_history(
    student_id: str,
    platform: Platform = Depends(verify_api_key),
    r: redis.Redis = Depends(get_redis),
) -> StudentHistoryResponse:
    await check_rate_limit(r, platform.api_key)
    student = await _resolve_student(platform, student_id)

    async with session_scope() as session:
        analyses_rows = (
            await session.execute(
                select(Analysis)
                .where(Analysis.student_id == student.id)
                .order_by(Analysis.created_at.desc())
                .limit(100)
            )
        ).scalars()
        generated_rows = (
            await session.execute(
                select(GeneratedTask)
                .where(GeneratedTask.student_id == student.id)
                .order_by(GeneratedTask.created_at.desc())
                .limit(100)
            )
        ).scalars()

        analyses = [
            StudentHistoryAnalysis(
                id=str(row.id),
                task_description=row.task_description,
                score=row.score,
                weak_spots=row.weak_spots,
                tags=row.tags,
                recommendations=row.recommendations,
                created_at=row.created_at.isoformat(),
            )
            for row in analyses_rows
        ]
        generated_tasks = [
            StudentHistoryGeneratedTask(
                id=str(row.id),
                analysis_id=str(row.analysis_id) if row.analysis_id else None,
                tags=row.tags,
                difficulty=row.difficulty,
                task=row.task_json,
                created_at=row.created_at.isoformat(),
            )
            for row in generated_rows
        ]

    return StudentHistoryResponse(student_id=student_id, analyses=analyses, generated_tasks=generated_tasks)


@router.get("/students/{student_id}/profile", response_model=StudentProfileResponse)
async def student_profile(
    student_id: str,
    platform: Platform = Depends(verify_api_key),
    r: redis.Redis = Depends(get_redis),
) -> StudentProfileResponse:
    await check_rate_limit(r, platform.api_key)
    student = await _resolve_student(platform, student_id)
    profile = await get_student_profile(r, student_id=str(student.id))
    if profile is None:
        raise HTTPException(status_code=404, detail="Student profile not found")
    return StudentProfileResponse(student_id=student_id, profile=profile)
