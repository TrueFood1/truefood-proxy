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

# Cache de sesiones para no re-autenticar cada llamada
session_cache = {}

@app.post("/proxy/{path:path}")
async def proxy(path: str, request: Request):
    body = await request.body()
    odoo_url = request.headers.get("x-odoo-url", "https://demotruefood.odoo.com").rstrip("/")

    if not any(odoo_url.startswith(u) for u in ALLOWED_ODOO_URLS):
        return JSONResponse({"error": "URL no permitida"}, status_code=403)

    auth = request.headers.get("authorization", "")
    user = ""
    password = ""
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            user, password = decoded.split(":", 1)
        except Exception:
            pass

    try:
        body_json = json.loads(body)
    except Exception:
        body_json = {}

    cache_key = f"{odoo_url}:{user}:{password}"
    
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        # Intentar con sesión cacheada primero
        cookies = session_cache.get(cache_key, {})
        
        if not cookies:
            # Autenticar para obtener cookies de sesión
            print(f"Authenticating {user} at {odoo_url}")
            auth_resp = await client.post(
                f"{odoo_url}/web/session/authenticate",
                json={
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {
                        "login": user,
                        "password": password
                    }
                },
                headers={"Content-Type": "application/json"}
            )
            
            auth_json = auth_resp.json()
            uid = auth_json.get("result", {}).get("uid")
            print(f"Auth result: uid={uid}, error={auth_json.get('error')}")
            
            if not uid:
                return JSONResponse(auth_json)
            
            cookies = dict(auth_resp.cookies)
            session_cache[cache_key] = cookies
            print(f"Got cookies: {list(cookies.keys())}")

        # Hacer la llamada real con las cookies de sesión
        resp = await client.post(
            f"{odoo_url}/{path}",
            content=body,
            headers={"Content-Type": "application/json"},
            cookies=cookies
        )
        
        print(f"Response status: {resp.status_code}")
        result = resp.json()
        
        # Si la sesión expiró, limpiar cache y reintentar
        if result.get("error", {}).get("code") == 100:
            print("Session expired, clearing cache")
            session_cache.pop(cache_key, None)
        
        return JSONResponse(result)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"status": "ok", "message": "True Food Proxy v5"}
