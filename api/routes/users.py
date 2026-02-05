from fastapi import APIRouter, HTTPException, Depends
from typing import List
from bson import ObjectId
from datetime import datetime
from api.core.database import get_database
from api.models.user import UserCreate, UserUpdate, UserResponse
from api.core.security import get_password_hash

router = APIRouter()

# Helper to fix MongoDB _id
def fix_id(user):
    user["id"] = str(user["_id"])
    return user

# 1. GET ALL USERS
@router.get("/", response_model=List[UserResponse])
async def get_users():
    db = get_database()
    users = await db["users"].find().to_list(100)
    return [fix_id(user) for user in users]

# 2. CREATE USER
@router.post("/", response_model=UserResponse)
async def create_user(user_in: UserCreate):
    db = get_database()
    
    # Check if email exists
    if await db["users"].find_one({"email": user_in.email}):
        raise HTTPException(status_code=400, detail="Email already registered")

    user_dict = user_in.dict()
    # Hash the password
    user_dict["hashed_password"] = get_password_hash(user_dict.pop("password"))
    user_dict["created_at"] = datetime.utcnow()
    
    new_user = await db["users"].insert_one(user_dict)
    created_user = await db["users"].find_one({"_id": new_user.inserted_id})
    return fix_id(created_user)

# 3. UPDATE USER
@router.put("/{user_id}", response_model=UserResponse)
async def update_user(user_id: str, user_in: UserUpdate):
    db = get_database()
    
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID")

    update_data = {k: v for k, v in user_in.dict().items() if v is not None}

    # If password is being updated, hash it
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

# 4. DELETE USER
@router.delete("/{user_id}")
async def delete_user(user_id: str):
    db = get_database()
    
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID")
        
    result = await db["users"].delete_one({"_id": ObjectId(user_id)})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
        
    return {"message": "User deleted successfully"}