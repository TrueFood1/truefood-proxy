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

    # Extraer usuario y api_key
    auth = request.headers.get("authorization", "")
    user = ""
    api_key = ""
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

    print(f"Path: {path}, Model: {model}, Method: {method}, User: {user}, DB: {db}")

    async with httpx.AsyncClient(timeout=30) as client:
        # Paso 1: Autenticar via /jsonrpc para obtener uid
        auth_payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "id": 1,
            "params": {
                "service": "common",
                "method": "authenticate",
                "args": [db, user, api_key, {}]
            }
        }
        auth_resp = await client.post(
            f"{odoo_url}/jsonrpc",
            json=auth_payload,
            headers={"Content-Type": "application/json"}
        )
        auth_json = auth_resp.json()
        uid = auth_json.get("result")
        print(f"Auth response: uid={uid}, error={auth_json.get('error')}")

        if not uid:
            return JSONResponse({
                "jsonrpc": "2.0",
                "error": {
                    "code": 100,
                    "message": "Authentication failed",
                    "data": {"message": str(auth_json.get("error", "Invalid credentials"))}
                }
            })

        # Paso 2: Ejecutar la llamada via /jsonrpc con uid y api_key
        exec_payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "id": 2,
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [db, uid, api_key, model, method, args, kwargs]
            }
        }
        exec_resp = await client.post(
            f"{odoo_url}/jsonrpc",
            json=exec_payload,
            headers={"Content-Type": "application/json"}
        )
        result = exec_resp.json()
        print(f"Execute result (first 200): {json.dumps(result)[:200]}")
        return JSONResponse(result)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"status": "ok", "message": "True Food Proxy v3"}
