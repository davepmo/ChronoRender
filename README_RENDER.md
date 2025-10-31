
# PyChrono 9.0.1 AST Gate — Render.com Only (no Cloudflare)

This package deploys a **PyChrono 9.0.1-only** AST validator service on Render.com.  
It enforces strict imports and a symbol allow-list for modules:
- `pychrono` → alias `chrono`
- `pychrono.vehicle` → alias `veh`
- `pychrono.irrlicht` → alias `irr`
- `pychrono.fea` → alias `fea`

## Contents
- `chrono_allowlist_dump.py` — generates `allowlist.json` from *your local* PyChrono 9.0.1 (+ FEA) install
- `chrono_ast_gate_v2.py` — static AST validator
- `sitecustomize.py` — optional runtime guard to block legacy attributes loudly
- `validate_cli.py` — local CLI validator
- `app.py` — FastAPI server exposing POST `/validate` and GET `/healthz`
- `requirements.txt` — service dependencies
- `render.yaml` — optional Render blueprint
- `openapi.yaml` — Custom GPT Action schema (point it to your Render URL)

---

## Step 0 — Build the allow list locally
Do this on the machine that has **PyChrono 9.0.1** (and FEA) installed so the list matches your build.
```bash
conda activate chrono9
python chrono_allowlist_dump.py --out allowlist.json       --modules pychrono pychrono.irrlicht pychrono.vehicle pychrono.fea
```
Commit/upload the generated `allowlist.json` along with this folder when deploying to Render.

---

## Step 1 — Deploy to Render (Web Service)
**Option A: via Dashboard**
1. Create a new **Web Service** from your Git repo or upload this folder (including `allowlist.json`).
2. Build Command:  
   `pip install -r requirements.txt`
3. Start Command:  
   `uvicorn app:app --host 0.0.0.0 --port $PORT`
4. Environment Variables:
   - `ALLOWLIST_PATH = allowlist.json`
   - `API_KEY = <strong-secret>` (recommended; the service will require an `Authorization: Bearer ...` header)
5. Health Check Path: `/healthz`

**Option B: render.yaml**
- Use the included `render.yaml` blueprint to create the same service configuration.

---

## Step 2 — Verify deployment
Open in a browser:
```
https://<your-service>.onrender.com/healthz
```
You should see JSON like:
```json
{ "ok": true, "allowlist_modules": ["pychrono", "pychrono.irrlicht", "pychrono.vehicle", "pychrono.fea"] }
```

---

## Step 3 — Test the validator
**curl (macOS/Linux)**
```bash
curl -X POST https://<your-service>.onrender.com/validate       -H "Content-Type: application/json"       -H "Authorization: Bearer <API_KEY>"       --data '{"code":"import pychrono as chrono\nimport pychrono.fea as fea\nprint(1)"}'
```

**Windows (CMD)**
```cmd
curl -X POST -H "Content-Type: application/json" -H "Authorization: Bearer <API_KEY>" ^
  --data "{"code":"import pychrono as chrono\nimport pychrono.fea as fea\nprint(1)"}" ^
  https://<your-service>.onrender.com/validate
```

**Windows (PowerShell)**
```powershell
$body = @{ code = "import pychrono as chrono`nimport pychrono.fea as fea`nprint(1)" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "https://<your-service>.onrender.com/validate" `
  -Headers @{ "Authorization"="Bearer <API_KEY>"; "Content-Type"="application/json" } `
  -Body $body
```

---

## Step 4 — Wire into your Custom GPT (no Cloudflare)
1. In your GPT’s **Actions** tab, upload `openapi.yaml`.
2. Set `servers[0].url` to your Render URL, e.g. `https://<your-service>.onrender.com`.
3. Add a default header for the Action calls:  
   `Authorization: Bearer <API_KEY>`
4. Add these **System** rules:
   - “Before returning any Python, call `validate_code`. If `ok=false`, repair and re-validate.”
   - “Use only PyChrono 9.0.1 symbols.”
   - “Allowed imports and aliases (strict):
     ```python
     import pychrono as chrono
     import pychrono.vehicle as veh
     import pychrono.irrlicht as irr
     import pychrono.fea as fea
     ```
     Never use `from pychrono import ...` or star-imports.”

---

## Local-only usage (optional)
You can still run the AST check and runtime guard locally for offline testing:
```bash
# Validate a file
python validate_cli.py --allowlist allowlist.json path/to/code.py

# Validate from stdin
echo "import pychrono as chrono" | python validate_cli.py --allowlist allowlist.json -

# Runtime guard (blocks legacy attributes loudly)
export PYTHONPATH="$PWD:$PYTHONPATH"
python -c "import pychrono; print('Runtime guard active')"
```

---

## Notes
- If you later use more PyChrono submodules, regenerate `allowlist.json` with the extra module names and redeploy.
- You can expand the legacy symbol blocklist inside `chrono_ast_gate_v2.py` and `sitecustomize.py` if you see new legacy names leaking in.
