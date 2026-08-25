from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from pymongo import MongoClient
from bson import ObjectId
import os
import hashlib
import uvicorn

app = FastAPI(title="User Service", version="1.0.0")

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongo:27017")
client = MongoClient(MONGO_URI)
db = client.shopsphere
users_collection = db.users

class User(BaseModel):
    username: str
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    username: str
    email: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "user-service"}

@app.post("/users/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(user: User):
    if users_collection.find_one({"email": user.email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user_doc = {
        "username": user.username,
        "email": user.email,
        "password": hash_password(user.password)
    }
    
    result = users_collection.insert_one(user_doc)
    
    return UserResponse(
        id=str(result.inserted_id),
        username=user.username,
        email=user.email
    )

@app.post("/users/login")
def login_user(login: LoginRequest):
    user = users_collection.find_one({
        "email": login.email,
        "password": hash_password(login.password)
    })
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    return {
        "message": "Login successful",
        "user_id": str(user["_id"]),
        "username": user["username"]
    }

@app.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: str):
    try:
        user = users_collection.find_one({"_id": ObjectId(user_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return UserResponse(
        id=str(user["_id"]),
        username=user["username"],
        email=user["email"]
    )

@app.get("/users")
def list_users(skip: int = 0, limit: int = 10):
    users = list(users_collection.find().skip(skip).limit(limit))
    return [
        {
            "id": str(user["_id"]),
            "username": user["username"],
            "email": user["email"]
        }
        for user in users
    ]

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)