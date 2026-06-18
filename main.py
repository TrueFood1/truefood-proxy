from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_ODOO_URLS = [
    "https://demotruefood.odoo.com",
    "https://truefood.odoo.com",
]

@app.post("/proxy/{path:path}")
async def proxy(path: str, request: Request):
    body = await request.body()
    odoo_url = request.headers.get("x-odoo-url", "https://demotruefood.odoo.com").rstrip("/")
    
    if not any(odoo_url.startswith(u) for u in ALLOWED_ODOO_URLS):
        return JSONResponse({"error": "URL no permitida"}, status_code=403)
    
    target = f"{odoo_url}/{path}"
    
    forward_headers = {"Content-Type": "application/json"}
    auth = request.headers.get("authorization")
    if auth:
        forward_headers["Authorization"] = auth
    
    print(f"Proxying to: {target}")
    print(f"Auth header present: {bool(auth)}")
    
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(target, content=body, headers=forward_headers)
    
    resp_json = resp.json()
    print(f"Odoo response status: {resp.status_code}")
    print(f"Odoo response: {json.dumps(resp_json)[:200]}")
    
    return JSONResponse(resp_json)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"status": "ok", "message": "True Food Proxy"}
