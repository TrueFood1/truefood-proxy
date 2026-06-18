from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
import json
import base64

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
    db = request.headers.get("x-odoo-db", "demotruefood")

    if not any(odoo_url.startswith(u) for u in ALLOWED_ODOO_URLS):
        return JSONResponse({"error": "URL no permitida"}, status_code=403)

    auth = request.headers.get("authorization", "")
    api_key = ""
    user = ""
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            user, api_key = decoded.split(":", 1)
        except Exception:
            pass

    try:
        body_json = json.loads(body)
    except Exception:
        body_json = {}

    params = body_json.get("params", {})
    model = params.get("model", "")
    method = params.get("method", "")
    args = params.get("args", [])
    kwargs = params.get("kwargs", {})

    print(f"Model: {model}, Method: {method}, User: {user}")

    async with httpx.AsyncClient(timeout=30) as client:
        # Usar REST API de Odoo con Bearer token (API key)
        # Disponible desde Odoo 16 en /api/method/
        # Para call_kw usar /api/call_kw
        rest_url = f"{odoo_url}/api/method/{model}.{method}"
        
        # Preparar payload para REST API
        rest_payload = {
            "args": args,
            "kwargs": kwargs
        }
        
        print(f"Trying REST API: {rest_url}")
        
        rest_resp = await client.post(
            rest_url,
            json=rest_payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "DATABASE": db
            }
        )
        
        print(f"REST response status: {rest_resp.status_code}")
        print(f"REST response: {rest_resp.text[:300]}")
        
        if rest_resp.status_code == 200:
            try:
                result = rest_resp.json()
                # Wrap in JSON-RPC format
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": result
                })
            except Exception:
                pass
        
        # Fallback: intentar con /web/dataset/call_kw pasando directamente
        # (funciona si Odoo acepta Bearer en ese endpoint)
        print("Trying /web/dataset/call_kw with Bearer token...")
        kw_resp = await client.post(
            f"{odoo_url}/web/dataset/call_kw",
            json={
                "jsonrpc": "2.0",
                "method": "call",
                "id": 1,
                "params": {
                    "model": model,
                    "method": method,
                    "args": args,
                    "kwargs": kwargs
                }
            },
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
        )
        
        print(f"call_kw Bearer status: {kw_resp.status_code}")
        result = kw_resp.json()
        print(f"call_kw result: {json.dumps(result)[:200]}")
        return JSONResponse(result)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"status": "ok", "message": "True Food Proxy v4"}
