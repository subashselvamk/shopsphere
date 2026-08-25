from fastapi import FastAPI, HTTPException, status, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pymongo import MongoClient
from bson import ObjectId
from typing import Optional
import os
import uvicorn
import uuid
from pathlib import Path

app = FastAPI(title="Product Service", version="1.0.0")

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
products_collection = db.products

# Create uploads directory if it doesn't exist
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

class Product(BaseModel):
    name: str
    description: str
    price: float
    stock: int
    category: str
    image_url: Optional[str] = None

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    stock: Optional[int] = None
    category: Optional[str] = None
    image_url: Optional[str] = None

class ProductResponse(BaseModel):
    id: str
    name: str
    description: str
    price: float
    stock: int
    category: str
    image_url: Optional[str] = None

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "product-service"}

@app.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(product: Product):
    product_doc = product.dict()
    result = products_collection.insert_one(product_doc)
    
    return ProductResponse(
        id=str(result.inserted_id),
        **product.dict()
    )

@app.get("/products/{product_id}", response_model=ProductResponse)
def get_product(product_id: str):
    try:
        product = products_collection.find_one({"_id": ObjectId(product_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    return ProductResponse(
        id=str(product["_id"]),
        name=product["name"],
        description=product["description"],
        price=product["price"],
        stock=product["stock"],
        category=product["category"],
        image_url=product.get("image_url")
    )

@app.get("/products")
def list_products(category: Optional[str] = None, skip: int = 0, limit: int = 20):
    query = {}
    if category:
        query["category"] = category
    
    products = list(products_collection.find(query).skip(skip).limit(limit))
    
    return [
        {
            "id": str(p["_id"]),
            "name": p["name"],
            "description": p["description"],
            "price": p["price"],
            "stock": p["stock"],
            "category": p["category"],
            "image_url": p.get("image_url")
        }
        for p in products
    ]

@app.put("/products/{product_id}", response_model=ProductResponse)
def update_product(product_id: str, product_update: ProductUpdate):
    try:
        obj_id = ObjectId(product_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    
    update_data = {k: v for k, v in product_update.dict().items() if v is not None}
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    result = products_collection.update_one(
        {"_id": obj_id},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    
    updated_product = products_collection.find_one({"_id": obj_id})
    
    return ProductResponse(
        id=str(updated_product["_id"]),
        name=updated_product["name"],
        description=updated_product["description"],
        price=updated_product["price"],
        stock=updated_product["stock"],
        category=updated_product["category"],
        image_url=updated_product.get("image_url")
    )

@app.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: str):
    try:
        obj_id = ObjectId(product_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    
    # Get product to delete associated image
    product = products_collection.find_one({"_id": obj_id})
    if product and product.get("image_url"):
        image_path = UPLOAD_DIR / product["image_url"].split("/")[-1]
        if image_path.exists():
            image_path.unlink()
    
    result = products_collection.delete_one({"_id": obj_id})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    
    return None

@app.post("/products/{product_id}/upload-image")
async def upload_product_image(product_id: str, file: UploadFile = File(...)):
    try:
        obj_id = ObjectId(product_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    
    # Check if product exists
    product = products_collection.find_one({"_id": obj_id})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Validate file type
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    
    # Generate unique filename
    file_extension = Path(file.filename).suffix
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = UPLOAD_DIR / unique_filename
    
    # Save file
    with open(file_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)
    
    # Delete old image if exists
    if product.get("image_url"):
        old_image_path = UPLOAD_DIR / product["image_url"].split("/")[-1]
        if old_image_path.exists():
            old_image_path.unlink()
    
    # Update product with image URL
    image_url = f"/uploads/{unique_filename}"
    products_collection.update_one(
        {"_id": obj_id},
        {"$set": {"image_url": image_url}}
    )
    
    return {"image_url": image_url}

@app.get("/uploads/{filename}")
async def get_image(filename: str):
    file_path = UPLOAD_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(file_path)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)