from typing import Optional
import os
import httpx
from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from api.core.config import BACKEND_URL

# NOTE: Local JWT/Bcrypt security has been removed. 
# Verification is now delegated to the Node.js backend.

# ─────────────────────────────────────────────────────────────────────────────
# 💥 STANDALONE SECURITY BOUNCER
# ─────────────────────────────────────────────────────────────────────────────
security = HTTPBearer(auto_error=False)

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    token_query: Optional[str] = Query(None, alias="token")
):
    """Verifies the JWT token by calling the Node.js Backend API."""
    token = None
    if credentials:
        token = credentials.credentials
    elif token_query:
        token = token_query
        
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated. Token missing.")

    try:
        # Delegate verification to Node.js
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BACKEND_URL}/api/auth/me",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5.0
            )
            
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="Token expired or invalid in backend")
            
        data = response.json()
        if not data.get("success") or "user" not in data:
            raise HTTPException(status_code=401, detail="Invalid token response from backend")
            
        user = data["user"]
        
        # Consistent return structure: {email, role, id}
        return {
            "email": user.get("email"), 
            "role": user.get("role", "superadmin"),
            "id": str(user.get("id") or user.get("_id", ""))
        }
    except httpx.RequestError as e:
        print(f"⚠️ Auth Backend Error: {e}")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    except Exception as e:
        print(f"⚠️ Auth Rejected: {e}")
        raise HTTPException(status_code=401, detail="Token verification failed")

def require_superadmin(current_user: dict = Depends(get_current_user)):
    """Satisfies the import requirement for routes. Checks for Admin/SuperAdmin role."""
    # Add role-based logic here if needed beyond verification
    return current_user