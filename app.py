# app.py
# FastAPI service for Render.com that lints and executes code.
# /lint returns validation only. /execute ALWAYS runs validator first.

import os, traceback
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from chrono_validator_v3 import validate_python

AUTH_KEY = os.environ.get("AUTH_KEY", "")
app = FastAPI(title="Chrono v9 Validator+Runner")

class CodeIn(BaseModel):
    code: str

def require_auth(x_auth_key: Optional[str]):
    if not AUTH_KEY:
        return
    if x_auth_key != AUTH_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

@app.post("/lint")
def lint(payload: CodeIn, x_auth_key: Optional[str] = Header(default=None)):
    require_auth(x_auth_key)
    ok, errors = validate_python(payload.code)
    return {"ok": ok, "errors": errors}

@app.post("/execute")
def execute(payload: CodeIn, x_auth_key: Optional[str] = Header(default=None)):
    require_auth(x_auth_key)
    ok, errors = validate_python(payload.code)
    if not ok:
        raise HTTPException(status_code=422, detail={"errors": errors})
    # If you actually execute code, sandbox it. For now, just confirm it passed.
    # (Most users proxy to your existing ChronoRender executor here.)
    return {"ok": True, "stdout": "", "stderr": "", "note": "Validation passed; execution stub"}
