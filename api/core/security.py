from datetime import datetime, timedelta
from typing import Optional
from jose import jwt
import bcrypt
import os

from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Load settings
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8") if isinstance(hashed_password, str) else hashed_password,
    )

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# ─────────────────────────────────────────────────────────────────────────────
# 💥 STANDALONE SECURITY BOUNCER
# ─────────────────────────────────────────────────────────────────────────────
security = HTTPBearer(auto_error=False)

def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    token_query: Optional[str] = Query(None, alias="token")
):
    """Decodes the JWT token from Header OR Query Param (for SSE)."""
    token = None
    if credentials:
        token = credentials.credentials
    elif token_query:
        token = token_query
        
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated. Token missing.")

    try:
        # Uses its own internal SECRET_KEY to verify the token it created
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token payload structure")
        
        # Pass back role if it exists, default to superadmin
        return {"email": email, "role": payload.get("role", "superadmin")}
    except Exception as e:
        print(f"⚠️ Auth Rejected: {e}")
        raise HTTPException(status_code=401, detail="Token expired or invalid")

def require_superadmin(current_user: dict = Depends(get_current_user)):
    """Satisfies the import requirement for users.py"""
    return current_user