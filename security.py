from datetime import datetime, timedelta, timezone
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET
from db import get_db
from models import User
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/auth/login')

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

def get_current_user(token: str=Depends(oauth2_scheme), db: Session=Depends(get_db)) -> User:
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail='JWT_SECRET is not set.')
    credentials_error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Could not validate credentials', headers={'WWW-Authenticate': 'Bearer'})
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        sub = payload.get('sub')
        if sub is None:
            raise credentials_error
        user_id = int(sub)
    except (JWTError, ValueError):
        raise credentials_error
    user = db.get(User, user_id)
    if user is None:
        raise credentials_error
    return user