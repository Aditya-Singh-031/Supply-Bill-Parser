from fastapi import APIRouter, HTTPException, Depends
from api.core.database import get_database
# 💥 Added get_password_hash to imports
from api.core.security import verify_password, create_access_token, get_password_hash 
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

    # 5. Generate Token
    access_token = create_access_token(data={"sub": user["email"]})
    
    # 6. Return Token + User Info (converting MongoDB _id to string)
    user["id"] = str(user["_id"])
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user
    }

# ─────────────────────────────────────────────────────────────────────────────
# 💥 TEMPORARY RECOVERY ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/setup-admin")
async def setup_admin():
    """Temporary endpoint to recreate the superadmin after a database wipe."""
    db = get_database()
    users_collection = db["users"]
    
    email = "superadmin@morsebiz.com"
    password = "SuperAdmin@9060"
    
    # Check if user already exists to prevent duplicates
    existing = await users_collection.find_one({"email": email})
    if existing:
        return {"message": "Admin user already exists in the database."}

    user_doc = {
        "email": email,
        "hashed_password": get_password_hash(password),
        "full_name": "Super Admin",
        "role": "superadmin",
        "status": "active",
        "created_at": datetime.utcnow(),
        "last_login": None
    }
    
    await users_collection.insert_one(user_doc)
    return {"message": f"Success! Superadmin {email} created."}