from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pymongo import MongoClient
from bson import ObjectId
from typing import List
import os
import httpx
import uvicorn
from datetime import datetime

app = FastAPI(title="Order Service", version="1.0.0")

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
orders_collection = db.orders

# Service URLs
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://user-service:8001")
PRODUCT_SERVICE_URL = os.getenv("PRODUCT_SERVICE_URL", "http://product-service:8002")

class OrderItem(BaseModel):
    product_id: str
    quantity: int

class Order(BaseModel):
    user_id: str
    items: List[OrderItem]

class OrderResponse(BaseModel):
    id: str
    user_id: str
    items: List[dict]
    total_amount: float
    status: str
    created_at: str

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "order-service"}

async def verify_user(user_id: str):
    """Verify user exists in User Service"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{USER_SERVICE_URL}/users/{user_id}")
            if response.status_code != 200:
                return False
            return True
        except:
            raise HTTPException(status_code=503, detail="User service unavailable")

async def get_product(product_id: str):
    """Get product details from Product Service"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{PRODUCT_SERVICE_URL}/products/{product_id}")
            if response.status_code == 200:
                return response.json()
            return None
        except:
            raise HTTPException(status_code=503, detail="Product service unavailable")

@app.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(order: Order):
    # Verify user exists
    user_exists = await verify_user(order.user_id)
    if not user_exists:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Verify products and calculate total
    order_items = []
    total_amount = 0.0
    
    for item in order.items:
        product = await get_product(item.product_id)
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
        
        if product["stock"] < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for product {product['name']}"
            )
        
        item_total = product["price"] * item.quantity
        total_amount += item_total
        
        order_items.append({
            "product_id": item.product_id,
            "product_name": product["name"],
            "quantity": item.quantity,
            "price": product["price"],
            "subtotal": item_total
        })
    
    # Create order
    order_doc = {
        "user_id": order.user_id,
        "items": order_items,
        "total_amount": total_amount,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat()
    }
    
    result = orders_collection.insert_one(order_doc)
    
    return OrderResponse(
        id=str(result.inserted_id),
        user_id=order.user_id,
        items=order_items,
        total_amount=total_amount,
        status="pending",
        created_at=order_doc["created_at"]
    )

@app.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: str):
    try:
        order = orders_collection.find_one({"_id": ObjectId(order_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid order ID format")
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    return OrderResponse(
        id=str(order["_id"]),
        user_id=order["user_id"],
        items=order["items"],
        total_amount=order["total_amount"],
        status=order["status"],
        created_at=order["created_at"]
    )

@app.get("/orders")
def list_orders(user_id: str = None, skip: int = 0, limit: int = 10):
    query = {}
    if user_id:
        query["user_id"] = user_id
    
    orders = list(orders_collection.find(query).skip(skip).limit(limit))
    
    return [
        {
            "id": str(o["_id"]),
            "user_id": o["user_id"],
            "items": o["items"],
            "total_amount": o["total_amount"],
            "status": o["status"],
            "created_at": o["created_at"]
        }
        for o in orders
    ]

@app.patch("/orders/{order_id}/status")
def update_order_status(order_id: str, status: str):
    try:
        obj_id = ObjectId(order_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid order ID format")
    
    valid_statuses = ["pending", "confirmed", "shipped", "delivered", "cancelled"]
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    result = orders_collection.update_one(
        {"_id": obj_id},
        {"$set": {"status": status}}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Order not found")
    
    return {"message": "Order status updated", "status": status}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)