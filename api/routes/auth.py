from fastapi import APIRouter, HTTPException, Depends
from api.core.database import get_database
from api.core.security import verify_password, create_access_token
from api.models.user import LoginRequest, Token, UserResponse
from datetime import datetime

router = APIRouter()

@router.post("/login", response_model=Token)
async def login(credentials: LoginRequest):
    db = get_database()
    users_collection = db["users"]

    # 1. Find user by email
    user = await users_collection.find_one({"email": credentials.email})
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    # 2. Check password hash
    if not verify_password(credentials.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    # 3. Check status
    if user.get("status") != "active":
        raise HTTPException(status_code=403, detail="Account is inactive")

    # 4. Update last login time
    await users_collection.update_one(
        {"_id": user["_id"]},
        {"$set": {"last_login": datetime.utcnow()}}
    )

    # ... previous code ...

    # 5. Generate Token
    # 💥 THE FIX: Inject the role into the JWT token payload
    access_token = create_access_token(
        data={
            "sub": user["email"], 
            "role": user.get("role", "admin") # Default to admin if missing
        }
    )
    
    # 6. Return Token + User Info 
    user["id"] = str(user["_id"])
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }