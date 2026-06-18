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

    print(f"Path: {path}, User: {user}, DB: {db}")

    # Para call_kw, reescribir usando /web/jsonrpc con api_key
    try:
        body_json = json.loads(body)
    except Exception:
        body_json = {}

    params = body_json.get("params", {})
    model = params.get("model", "")
    method = params.get("method", "")
    args = params.get("args", [])
    kwargs = params.get("kwargs", {})

    # Usar /web/dataset/call_kw pero con autenticación via api_key en el header HTTP
    # Odoo acepta api_key como contraseña en Basic Auth para XML-RPC pero no para JSON-RPC
    # Solución: inyectar uid en el contexto después de verificar con XML-RPC

    # Verificar usuario via XML-RPC con api_key
    xmlrpc_auth_body = f"""<?xml version='1.0'?>
<methodCall>
  <methodName>authenticate</methodName>
  <params>
    <param><value><string>{db}</string></value></param>
    <param><value><string>{user}</string></value></param>
    <param><value><string>{api_key}</string></value></param>
    <param><value><struct></struct></value></param>
  </params>
</methodCall>"""

    async with httpx.AsyncClient(timeout=30) as client:
        # Autenticar via XML-RPC
        auth_resp = await client.post(
            f"{odoo_url}/xmlrpc/2/common",
            content=xmlrpc_auth_body.encode(),
            headers={"Content-Type": "text/xml"}
        )
        
        print(f"XML-RPC auth status: {auth_resp.status_code}")
        auth_text = auth_resp.text
        
        # Extraer uid del response XML
        uid = None
        if "<int>" in auth_text:
            try:
                uid = int(auth_text.split("<int>")[1].split("</int>")[0])
            except Exception:
                pass
        
        print(f"UID from XML-RPC: {uid}")
        
        if not uid:
            return JSONResponse({
                "jsonrpc": "2.0",
                "error": {
                    "code": 100,
                    "message": "Authentication failed - invalid API key or user"
                }
            })

        # Ejecutar llamada via XML-RPC
        # Convertir args a XML-RPC
        args_xml = ""
        for arg in args:
            args_xml += f"<param><value>{python_to_xmlrpc(arg)}</value></param>"
        
        kwargs_xml = dict_to_xmlrpc(kwargs)
        
        execute_body = f"""<?xml version='1.0'?>
<methodCall>
  <methodName>execute_kw</methodName>
  <params>
    <param><value><string>{db}</string></value></param>
    <param><value><int>{uid}</int></value></param>
    <param><value><string>{api_key}</string></value></param>
    <param><value><string>{model}</string></value></param>
    <param><value><string>{method}</string></value></param>
    <param><value><array><data>{args_xml}</data></array></value></param>
    <param><value>{kwargs_xml}</value></param>
  </params>
</methodCall>"""

        exec_resp = await client.post(
            f"{odoo_url}/xmlrpc/2/object",
            content=execute_body.encode(),
            headers={"Content-Type": "text/xml"}
        )
        
        print(f"Execute status: {exec_resp.status_code}")
        exec_text = exec_resp.text
        print(f"Execute response (first 300): {exec_text[:300]}")
        
        # Convertir XML-RPC response a JSON-RPC format
        result = xmlrpc_to_python(exec_text)
        
        if isinstance(result, dict) and "faultCode" in result:
            return JSONResponse({
                "jsonrpc": "2.0",
                "error": {
                    "code": result.get("faultCode", 500),
                    "message": result.get("faultString", "Error"),
                    "data": {"message": result.get("faultString", "Error")}
                }
            })
        
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": 1,
            "result": result
        })

def python_to_xmlrpc(val):
    if val is None:
        return "<boolean>0</boolean>"
    elif isinstance(val, bool):
        return f"<boolean>{'1' if val else '0'}</boolean>"
    elif isinstance(val, int):
        return f"<int>{val}</int>"
    elif isinstance(val, float):
        return f"<double>{val}</double>"
    elif isinstance(val, str):
        escaped = val.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"<string>{escaped}</string>"
    elif isinstance(val, list):
        items = "".join(f"<value>{python_to_xmlrpc(i)}</value>" for i in val)
        return f"<array><data>{items}</data></array>"
    elif isinstance(val, dict):
        return dict_to_xmlrpc(val)
    return f"<string>{str(val)}</string>"

def dict_to_xmlrpc(d):
    if not isinstance(d, dict):
        return python_to_xmlrpc(d)
    members = ""
    for k, v in d.items():
        escaped_k = str(k).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        members += f"<member><name>{escaped_k}</name><value>{python_to_xmlrpc(v)}</value></member>"
    return f"<struct>{members}</struct>"

def xmlrpc_to_python(xml_text):
    """Convert XML-RPC response to Python object (basic implementation)"""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_text)
        # Check for fault
        fault = root.find(".//fault")
        if fault is not None:
            fault_val = parse_value(fault.find("value"))
            return fault_val
        # Get response value
        val = root.find(".//params/param/value")
        if val is not None:
            return parse_value(val)
        return None
    except Exception as e:
        print(f"XML parse error: {e}")
        return None

def parse_value(elem):
    if elem is None:
        return None
    # Check direct text (string shorthand)
    child = list(elem)
    if not child:
        return elem.text or ""
    child = child[0]
    tag = child.tag
    text = child.text or ""
    if tag == "string":
        return text
    elif tag == "int" or tag == "i4" or tag == "i8":
        return int(text)
    elif tag == "double":
        return float(text)
    elif tag == "boolean":
        return text.strip() == "1"
    elif tag == "nil":
        return None
    elif tag == "array":
        data = child.find("data")
        if data is not None:
            return [parse_value(v) for v in data.findall("value")]
        return []
    elif tag == "struct":
        result = {}
        for member in child.findall("member"):
            name = member.find("name")
            val = member.find("value")
            if name is not None and val is not None:
                result[name.text] = parse_value(val)
        return result
    return text

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"status": "ok", "message": "True Food Proxy v2"}
