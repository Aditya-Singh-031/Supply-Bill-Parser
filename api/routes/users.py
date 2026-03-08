from fastapi import APIRouter, HTTPException, Depends
from typing import List
from bson import ObjectId
from datetime import datetime
from api.core.database import get_database
from api.models.user import UserCreate, UserUpdate, UserResponse
# 💥 NEW: Import the bouncer
from api.core.security import get_password_hash, require_superadmin

router = APIRouter()

def fix_id(user):
    user = dict(user)
    user["id"] = str(user["_id"])
    user["created_at"] = user.get("created_at") or user.get("createdAt")
    user.pop("_id", None)
    user.pop("password", None)
    user.pop("hashed_password", None)
    return user

# 1. GET ALL USERS (Protected)
# 💥 Added Depends(require_superadmin)
@router.get("/", response_model=List[UserResponse], dependencies=[Depends(require_superadmin)])
async def get_users():
    db = get_database()
    users = await db["users"].find().to_list(100)
    return [fix_id(user) for user in users]

# 2. CREATE USER (Protected)
@router.post("/", response_model=UserResponse, dependencies=[Depends(require_superadmin)])
async def create_user(user_in: UserCreate):
    db = get_database()
    
    if await db["users"].find_one({"email": user_in.email}):
        raise HTTPException(status_code=400, detail="Email already registered")

    user_dict = user_in.dict()
    user_dict["hashed_password"] = get_password_hash(user_dict.pop("password"))
    user_dict["created_at"] = datetime.utcnow()
    
    new_user = await db["users"].insert_one(user_dict)
    created_user = await db["users"].find_one({"_id": new_user.inserted_id})
    return fix_id(created_user)

# 3. UPDATE USER (Protected)
@router.put("/{user_id}", response_model=UserResponse, dependencies=[Depends(require_superadmin)])
async def update_user(user_id: str, user_in: UserUpdate):
    db = get_database()
    
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID")

    update_data = {k: v for k, v in user_in.dict().items() if v is not None}

    if "password" in update_data:
        update_data["hashed_password"] = get_password_hash(update_data.pop("password"))

    if not update_data:
        raise HTTPException(status_code=400, detail="No data to update")

    result = await db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
        
    updated_user = await db["users"].find_one({"_id": ObjectId(user_id)})
    return fix_id(updated_user)

# 4. DELETE USER (Protected)
@router.delete("/{user_id}", dependencies=[Depends(require_superadmin)])
async def delete_user(user_id: str):
    db = get_database()
    
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID")
        
    result = await db["users"].delete_one({"_id": ObjectId(user_id)})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
        
    return {"message": "User deleted successfully"}