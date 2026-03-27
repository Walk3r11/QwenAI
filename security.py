from datetime import datetime, timedelta, timezone
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET
from db import SessionLocal, get_db
from models import User
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/auth/login')

def _credentials_error() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Could not validate credentials', headers={'WWW-Authenticate': 'Bearer'})

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def create_access_token(user_id: int) -> str:
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail='JWT_SECRET is not set.')
    exp = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {'sub': str(user_id), 'exp': exp}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_access_token_user_id(token: str) -> int:
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail='JWT_SECRET is not set.')
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        sub = payload.get('sub')
        if sub is None:
            raise _credentials_error()
        return int(sub)
    except (JWTError, ValueError):
        raise _credentials_error()

def get_current_user(token: str=Depends(oauth2_scheme), db: Session=Depends(get_db)) -> User:
    user_id = decode_access_token_user_id(token)
    user = db.get(User, user_id)
    if user is None:
        raise _credentials_error()
    return user

def get_current_user_id_for_stream(token: str=Depends(oauth2_scheme)) -> int:
    """For StreamingResponse routes: DB session is opened and closed before the stream runs (avoids idle SSL drops on Neon)."""
    user_id = decode_access_token_user_id(token)
    db = SessionLocal()
    try:
        if db.get(User, user_id) is None:
            raise _credentials_error()
        return user_id
    finally:
        db.close()