from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class AuthRegisterResponse(BaseModel):
    user_id: uuid.UUID
    access_token: str
    token_type: str = "bearer"


class TokenRequest(BaseModel):
    user_id: uuid.UUID = Field(..., description="Registered user UUID")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: uuid.UUID
