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
    
    if not any(odoo_url.startswith(u) for u in ALLOWED_ODOO_URLS):
        return JSONResponse({"error": "URL no permitida"}, status_code=403)

    # Extraer usuario y api_key del header Authorization
    auth = request.headers.get("authorization", "")
    user = ""
    api_key = ""
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            user, api_key = decoded.split(":", 1)
        except Exception:
            pass

    # Parsear el body para inyectar la autenticación en el contexto
    try:
        body_json = json.loads(body)
    except Exception:
        body_json = {}

    # Para call_kw, usar /web/dataset/call_kw con autenticación via session
    # Primero autenticar para obtener session
    target = f"{odoo_url}/{path}"
    
    print(f"Proxying to: {target}")
    print(f"User: {user}, API key present: {bool(api_key)}")

    # Autenticar con Odoo para obtener cookies de sesión
    async with httpx.AsyncClient(timeout=30) as client:
        # Login con API key como password
        login_resp = await client.post(
            f"{odoo_url}/web/session/authenticate",
            json={
                "jsonrpc": "2.0",
                "method": "call",
                "params": {
                    "db": request.headers.get("x-odoo-db", "demotruefood"),
                    "login": user,
                    "password": api_key
                }
            },
            headers={"Content-Type": "application/json"}
        )
        
        print(f"Login status: {login_resp.status_code}")
        login_json = login_resp.json()
        
        if login_json.get("error") or not login_json.get("result", {}).get("uid"):
            print(f"Login failed: {json.dumps(login_json)[:200]}")
            return JSONResponse(login_json)
        
        print(f"Login OK, uid: {login_json['result']['uid']}")
        
        # Usar las cookies de sesión para la llamada real
        session_cookies = login_resp.cookies
        
        resp = await client.post(
            target,
            content=body,
            headers={"Content-Type": "application/json"},
            cookies=session_cookies
        )
    
    resp_json = resp.json()
    print(f"Final response: {json.dumps(resp_json)[:200]}")
    
    return JSONResponse(resp_json)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"status": "ok", "message": "True Food Proxy"}
