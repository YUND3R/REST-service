from __future__ import annotations
from typing import Annotated, NoReturn
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from edu_ml.auth_jwt import create_access_token
from edu_ml.schemas import TokenResponse
from edu_ml.settings_auth import get_auth_settings
router = APIRouter()

@router.post('/auth/token', response_model=TokenResponse)
async def oauth2_token(form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> TokenResponse:
    s = get_auth_settings()
    if not s.auth_enabled:
        raise HTTPException(status_code=503, detail='AUTH_ENABLED=false')
    users = s.parsed_passwords()
    if form.username not in users or users[form.username] != form.password:
        raise HTTPException(status_code=401, detail='Неверный логин или пароль')
    token = create_access_token(subject=form.username)
    return TokenResponse(access_token=token, token_type='bearer')

@router.get('/auth/oauth2/placeholders/authorize')
async def oauth2_authorize_not_implemented() -> NoReturn:
    raise HTTPException(status_code=501, detail='Authorization Code с внешним IdP не настроен; используйте POST /auth/token')
