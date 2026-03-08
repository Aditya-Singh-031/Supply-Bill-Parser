from datetime import datetime, timedelta
from typing import Optional
from jose import jwt
import bcrypt
import os

# 💥 NEW IMPORTS for the Security Checkpoint
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Load settings
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check if the entered password matches the stored hash"""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8") if isinstance(hashed_password, str) else hashed_password,
    )

def get_password_hash(password: str) -> str:
    """Scramble the password before saving to DB"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Generate a JWT token for the user session"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# ... keep existing verify_password, get_password_hash, create_access_token functions ...

# ─────────────────────────────────────────────────────────────────────────────
# 💥 NEW: ROLE-BASED ACCESS CONTROL (RBAC) GUARDS
# ─────────────────────────────────────────────────────────────────────────────
security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Decodes the JWT token and extracts the user's email and role."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        role: str = payload.get("role")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid authentication token")
        return {"email": email, "role": role}
    except Exception:
        raise HTTPException(status_code=401, detail="Could not validate credentials")

def require_superadmin(current_user: dict = Depends(get_current_user)):
    """Bouncer function: Rejects request if the user is not a super admin."""
    # Check for both variations just in case (superadmin vs super-admin)
    if current_user.get("role") not in ["superadmin", "super-admin"]:
        raise HTTPException(
            status_code=403, 
            detail="Forbidden: This action requires Super Admin privileges."
        )
    return current_user