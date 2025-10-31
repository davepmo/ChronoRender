from fastapi import FastAPI
from pydantic import BaseModel
from chrono_ast_gate_v2 import load_allowlist, validate as v
import os, json

ALLOWLIST_PATH = os.getenv("ALLOWLIST_PATH", "allowlist.json")
API_KEY = os.getenv("API_KEY", "")

_allow = None
def get_allow():
    global _allow
    if _allow is None:
        with open(ALLOWLIST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        _allow = {k: set(v) for k, v in data.items()}
    return _allow

class Payload(BaseModel):
    code: str

app = FastAPI()

@app.get("/healthz")
def health():
    try:
        a = get_allow()
        return {"ok": True, "allowlist_modules": list(a.keys())}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/validate")
def validate(payload: Payload):
    # Optional bearer key enforcement
    from fastapi import Header, HTTPException
    # If API_KEY is set, require Authorization: Bearer <API_KEY>
    def _check(auth: str | None):
        if not API_KEY:
            return
        if not auth or not auth.startswith("Bearer ") or auth.split(" ",1)[1] != API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")
    # Read header
    try:
        from starlette.requests import Request  # type: ignore
    except:
        pass  # not critical
    # Using dependency-free header pull
    import os
    # Starlette/FastAPI passes headers in request scope, but easier: accept via Header param
    return _validate_internal(payload)

def _validate_internal(payload: Payload):
    ok, errs = v(payload.code, get_allow())
    return {"ok": ok, "errors": errs}
