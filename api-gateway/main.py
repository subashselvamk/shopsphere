from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, Response
import httpx
import os
import uvicorn
from pathlib import Path

app = FastAPI(title="API Gateway", version="1.0.0")

# Determine frontend path - check both relative to this file and in the app directory (for Docker)
frontend_path = None
possible_paths = [
    Path(__file__).parent.parent / "frontend",  # When running from project root
    Path(__file__).parent / "frontend",  # When running in Docker
]

for path in possible_paths:
    if path.exists() and (path / "index.html").exists():
        frontend_path = path
        break

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Service URLs
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://user-service:8001")
PRODUCT_SERVICE_URL = os.getenv("PRODUCT_SERVICE_URL", "http://product-service:8002")
ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order-service:8003")

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "api-gateway"}

@app.get("/health/all")
async def health_check_all():
    """Check health of all services"""
    services = {
        "user-service": f"{USER_SERVICE_URL}/health",
        "product-service": f"{PRODUCT_SERVICE_URL}/health",
        "order-service": f"{ORDER_SERVICE_URL}/health"
    }
    
    results = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for service_name, url in services.items():
            try:
                response = await client.get(url)
                results[service_name] = response.json() if response.status_code == 200 else {"status": "unhealthy"}
            except:
                results[service_name] = {"status": "unavailable"}
    
    return {
        "gateway": {"status": "healthy"},
        "services": results
    }

async def proxy_request(service_url: str, path: str, request: Request):
    """Generic proxy function to forward requests to microservices"""
    url = f"{service_url}{path}"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Check if this is a multipart/form-data request (file upload)
            content_type = request.headers.get("content-type", "")
            if "multipart/form-data" in content_type:
                # Handle file upload
                form_data = await request.form()
                files = {}
                data = {}
                
                for key, value in form_data.items():
                    if hasattr(value, 'filename') and hasattr(value, 'read'):
                        # It's a file upload
                        file_content = await value.read()
                        files[key] = (value.filename or "file", file_content, value.content_type or "application/octet-stream")
                    else:
                        data[key] = value
                
                # Use files and data parameters for multipart upload
                if files:
                    response = await client.request(
                        method=request.method,
                        url=url,
                        params=request.query_params,
                        files=files,
                        data=data if data else None,
                        headers={k: v for k, v in request.headers.items() if k.lower() not in ["host", "content-type", "content-length"]}
                    )
                else:
                    # No files, just form data
                    response = await client.request(
                        method=request.method,
                        url=url,
                        params=request.query_params,
                        data=data,
                        headers={k: v for k, v in request.headers.items() if k.lower() not in ["host", "content-type", "content-length"]}
                    )
            else:
                # Get request body if present
                body = None
                if request.method in ["POST", "PUT", "PATCH"]:
                    body = await request.body()
                
                # Forward request
                response = await client.request(
                    method=request.method,
                    url=url,
                    content=body,
                    params=request.query_params,
                    headers={k: v for k, v in request.headers.items() if k.lower() != "host"}
                )
            
            # Handle empty responses (like 204 No Content)
            if response.status_code == 204:
                return Response(status_code=204)
            
            # Handle image/file responses
            content_type = response.headers.get("content-type", "")
            if "image/" in content_type or "application/octet-stream" in content_type:
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    media_type=content_type,
                    headers={k: v for k, v in response.headers.items() if k.lower() not in ["content-encoding", "transfer-encoding"]}
                )
            
            # Handle empty response body
            if not response.text:
                return JSONResponse(content={}, status_code=response.status_code)
            
            # Try to parse JSON, fallback to text if not JSON
            try:
                content = response.json()
            except:
                content = {"detail": response.text}
            
            return JSONResponse(
                content=content,
                status_code=response.status_code
            )
        
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Service timeout")
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Service unavailable")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

# User Service Routes
@app.api_route("/api/users/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def user_service_proxy(path: str, request: Request):
    return await proxy_request(USER_SERVICE_URL, f"/users/{path}", request)

@app.post("/api/users/register")
async def register_user(request: Request):
    return await proxy_request(USER_SERVICE_URL, "/users/register", request)

@app.post("/api/users/login")
async def login_user(request: Request):
    return await proxy_request(USER_SERVICE_URL, "/users/login", request)

@app.get("/api/users")
async def list_users(request: Request):
    return await proxy_request(USER_SERVICE_URL, "/users", request)

# Product Service Routes
@app.api_route("/api/products/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def product_service_proxy(path: str, request: Request):
    return await proxy_request(PRODUCT_SERVICE_URL, f"/products/{path}", request)

@app.get("/api/products")
async def list_products(request: Request):
    return await proxy_request(PRODUCT_SERVICE_URL, "/products", request)

@app.post("/api/products")
async def create_product(request: Request):
    return await proxy_request(PRODUCT_SERVICE_URL, "/products", request)

# Handle file uploads for product images
@app.post("/api/products/{product_id}/upload-image")
async def upload_product_image(product_id: str, request: Request):
    return await proxy_request(PRODUCT_SERVICE_URL, f"/products/{product_id}/upload-image", request)

# Proxy image requests from product service
@app.get("/api/uploads/{filename:path}")
async def get_product_image(filename: str, request: Request):
    return await proxy_request(PRODUCT_SERVICE_URL, f"/uploads/{filename}", request)

# Also handle /uploads directly (for image URLs that use /uploads/...)
@app.get("/uploads/{filename:path}")
async def get_product_image_direct(filename: str, request: Request):
    return await proxy_request(PRODUCT_SERVICE_URL, f"/uploads/{filename}", request)

# Order Service Routes
@app.api_route("/api/orders/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def order_service_proxy(path: str, request: Request):
    return await proxy_request(ORDER_SERVICE_URL, f"/orders/{path}", request)

@app.get("/api/orders")
async def list_orders(request: Request):
    return await proxy_request(ORDER_SERVICE_URL, "/orders", request)

@app.post("/api/orders")
async def create_order(request: Request):
    return await proxy_request(ORDER_SERVICE_URL, "/orders", request)

# Serve frontend - this route should be defined last so API routes take precedence
@app.get("/")
def serve_index():
    """Serve the frontend index.html file"""
    if frontend_path:
        index_path = frontend_path / "index.html"
        if index_path.exists():
            return FileResponse(
                str(index_path),
                media_type="text/html"
            )
    
    # Fallback if frontend not found
    return {
        "message": "ShopSphere API Gateway",
        "version": "1.0.0",
        "endpoints": {
            "users": "/api/users",
            "products": "/api/products",
            "orders": "/api/orders",
            "health": "/health",
            "health_all": "/health/all"
        }
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)