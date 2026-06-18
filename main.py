from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import httpx

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ODOO_URLS = [
    "https://demotruefood.odoo.com",
    "https://truefood.odoo.com",
]

@app.post("/proxy/{path:path}")
async def proxy(path: str, request: Request):
    body = await request.body()
    headers = dict(request.headers)
    
    # Obtener el host de Odoo del header o del body
    odoo_url = headers.get("x-odoo-url", "https://demotruefood.odoo.com")
    
    # Solo permitir URLs de Odoo conocidas
    if not any(odoo_url.startswith(u) for u in ODOO_URLS):
        return {"error": "URL no permitida"}
    
    target = f"{odoo_url}/{path}"
    
    # Remover headers que no deben pasarse
    headers.pop("host", None)
    headers.pop("content-length", None)
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            target,
            content=body,
            headers=headers,
            timeout=30
        )
    
    return resp.json()

@app.get("/health")
async def health():
    return {"status": "ok"}
