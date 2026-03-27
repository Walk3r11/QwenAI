import re
import secrets
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import ALLOW_PC_SCRIPT_SIGNUP, AUTH_SIGNUP_IMMEDIATE_TOKEN, GOOGLE_WEB_CLIENT_ID, PC_SCAN_SHARED_SECRET
from db import get_db
from email_service import send_verification_email
from models import User
from schemas import (
    AuthResponse,
    ChangePasswordRequest,
    GoogleAuthRequest,
    LoginRequest,
    SignupRequest,
    SignupResponse,
    UpdateProfileRequest,
    UserOut,
    VerifyRequest,
)
from security import create_access_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix='/auth', tags=['auth'])
_PC_SCRIPT_EMAIL = re.compile(r'^pc_[0-9a-f]{8,64}@example\.com$', re.I)


def _instant_signup_email(email: str) -> bool:
    return bool(AUTH_SIGNUP_IMMEDIATE_TOKEN or (ALLOW_PC_SCRIPT_SIGNUP and _PC_SCRIPT_EMAIL.match(email.strip())))


@router.post('/pc-scan-token', response_model=AuthResponse)
def pc_scan_token(authorization: str | None=Header(default=None), db: Session=Depends(get_db)):
    if not PC_SCAN_SHARED_SECRET:
        raise HTTPException(status_code=404, detail='Not Found')
    got = (authorization or '').strip()
    if got.startswith('Bearer '):
        got = got[7:].strip()
    if got != PC_SCAN_SHARED_SECRET:
        raise HTTPException(status_code=401, detail='Unauthorized')
    email = f'pc_{uuid.uuid4().hex}@example.com'
    pw = secrets.token_urlsafe(32)
    user = User(email=email, name='PC scan', hashed_password=hash_password(pw), is_verified=True, verification_code=None)
    db.add(user)
    db.commit()
    db.refresh(user)
    tok = create_access_token(user.id)
    return AuthResponse(access_token=tok, token_type='bearer', user=UserOut.model_validate(user))


@router.post('/signup', response_model=SignupResponse | AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, background_tasks: BackgroundTasks, db: Session=Depends(get_db)):
    em = payload.email.lower()
    instant = _instant_signup_email(em)
    existing = db.scalar(select(User).where(User.email == em))
    code = ''.join(secrets.choice('0123456789') for _ in range(6))
    if existing:
        if existing.is_verified:
            raise HTTPException(status_code=409, detail='Email already registered.')
        if instant:
            existing.name = payload.name.strip()
            existing.hashed_password = hash_password(payload.password)
            existing.is_verified = True
            existing.verification_code = None
            db.commit()
            db.refresh(existing)
            tok = create_access_token(existing.id)
            return AuthResponse(access_token=tok, token_type='bearer', user=UserOut.model_validate(existing))
        existing.name = payload.name.strip()
        existing.hashed_password = hash_password(payload.password)
        existing.verification_code = code
        db.commit()
        background_tasks.add_task(send_verification_email, existing.email, existing.name, code)
        return SignupResponse(message='Verification email resent.', email=existing.email)
    user = User(email=em, name=payload.name.strip(), hashed_password=hash_password(payload.password), verification_code=None if instant else code, is_verified=bool(instant))
    db.add(user)
    db.commit()
    db.refresh(user)
    if instant:
        tok = create_access_token(user.id)
        return AuthResponse(access_token=tok, token_type='bearer', user=UserOut.model_validate(user))
    background_tasks.add_task(send_verification_email, user.email, user.name, code)
    return SignupResponse(message='Verification email sent.', email=user.email)


@router.post('/verify', response_model=AuthResponse)
def verify(payload: VerifyRequest, db: Session=Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user:
        raise HTTPException(status_code=404, detail='User not found.')
    if user.is_verified:
        raise HTTPException(status_code=400, detail='User is already verified.')
    if user.verification_code != payload.code:
        raise HTTPException(status_code=400, detail='Invalid verification code.')
    user.is_verified = True
    user.verification_code = None
    db.commit()
    token = create_access_token(user.id)
    return AuthResponse(access_token=token, token_type='bearer', user=UserOut.model_validate(user))


@router.post('/login', response_model=AuthResponse)
def login(payload: LoginRequest, db: Session=Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail='Invalid email or password.')
    if not user.is_verified:
        raise HTTPException(status_code=403, detail='Email not verified. Please verify your email first.')
    token = create_access_token(user.id)
    return AuthResponse(access_token=token, token_type='bearer', user=UserOut.model_validate(user))


@router.post("/google", response_model=AuthResponse)
def google_auth(payload: GoogleAuthRequest, db: Session = Depends(get_db)):
    from google.oauth2 import id_token
    from google.auth.transport import requests
    import os

    print(f"[DEBUG] Verification attempt with WEB_CLIENT_ID: {GOOGLE_WEB_CLIENT_ID}")
    
    try:
        idinfo = id_token.verify_oauth2_token(payload.id_token, requests.Request(), GOOGLE_WEB_CLIENT_ID)
    except ValueError as e:
        print(f"[DEBUG] Google token verification failed: {str(e)}")
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {str(e)}")

    email = idinfo.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Google token does not contain an email.")

    user = db.scalar(select(User).where(User.email == email.lower()))
    if not user:
        # Create user automatically
        name = idinfo.get("name", "SnapChef User")
        # Generate a random impossible password so they can't login via normal password route
        import uuid
        user = User(
            email=email.lower(),
            name=name.strip(),
            hashed_password=hash_password(str(uuid.uuid4())),
            verification_code=None,
            is_verified=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif not user.is_verified:
        # If they previously tried to sign up but didn't verify, verifying via Google overrides it
        user.is_verified = True
        user.verification_code = None
        db.commit()

    token = create_access_token(user.id)
    return AuthResponse(access_token=token, token_type="bearer", user=UserOut.model_validate(user))



@router.get('/me', response_model=UserOut)
def me(current_user: User=Depends(get_current_user)):
    return UserOut.model_validate(current_user)



@router.patch('/me', response_model=UserOut)
def update_profile(payload: UpdateProfileRequest, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    current_user.name = payload.name.strip()
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return UserOut.model_validate(current_user)


@router.post('/change-password', status_code=status.HTTP_204_NO_CONTENT)
def change_password(payload: ChangePasswordRequest, db: Session=Depends(get_db), current_user: User=Depends(get_current_user)):
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail='Current password is incorrect.')
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail='New password must be different.')
    current_user.hashed_password = hash_password(payload.new_password)
    db.add(current_user)
    db.commit()
    return None


@router.delete('/me', status_code=status.HTTP_204_NO_CONTENT)
def delete_me(current_user: User=Depends(get_current_user), db: Session=Depends(get_db)):
    db.delete(current_user)
    db.commit()
    return None
