# chrono_ast_gate_v2.py
"""
AST validator (v2.3) for PyChrono 9.0.1-only code, with default-aware overload checking.

Enforces:
  - Only these imports (with aliases) are allowed:
        import pychrono as chrono
        import pychrono.vehicle as veh
        import pychrono.irrlicht as irr
        import pychrono.fea as fea
  - No star-imports or "from pychrono.* import X".
  - Attribute access must exist in 9.0.1 allowlist.
  - Constructor calls are checked against allowlisted overloads:
      * Matches by TYPE (enum, double/int, bool, ChContactMaterial)
      * Respects DEFAULT parameters (N <= M and (M-N) <= defaults)
      * Supports positional + keyword arguments
"""

from __future__ import annotations
import ast, json, argparse, sys, re
from typing import Any, Dict, List, Tuple

# Allowed import roots and required aliases
PYCHRONO_ROOTS = {
    "pychrono": "chrono",
    "pychrono.vehicle": "veh",
    "pychrono.irrlicht": "irr",
    "pychrono.fea": "fea",
}

# Hard block of legacy-era names you don't want used at all
LEGACY_BLOCKLIST = {
    "ChBodyAuxRef", "ChLinkEngine", "ChSharedPtr", "ChSystemSMC7",
    "ChSystemNSC7", "ChVectorDynamic", "ChMatrix33", "ChShared",
}

# ---------- allowlist loader ----------

def load_allowlist(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # "modules": {mod: [names...]}, "overloads": { "pychrono.core.ChBodyEasyCylinder":[{"args":[...], "defaults":2}, ...] }, "enums":[...]
    modules = {k: set(v) for k, v in raw.get("modules", {}).items()}
    enums = set(raw.get("enums", []))

    # Accept either list-of-lists (old) or list-of-dicts with defaults (new)
    normalized_ov: Dict[str, List[Dict[str, Any]]] = {}
    for k, v in raw.get("overloads", {}).items():
        items = []
        for ov in v:
            if isinstance(ov, dict):
                args = ov.get("args", [])
                defaults = int(ov.get("defaults", 0))
            else:
                args = list(ov)
                defaults = 0
            items.append({"args": args, "defaults": defaults})
        normalized_ov[k] = items

    return {"modules": modules, "overloads": normalized_ov, "enums": enums}

# ---------- AST helpers ----------

def _resolve_attr_chain(node: ast.AST) -> List[str]:
    out: List[str] = []
    while isinstance(node, ast.Attribute):
        out.insert(0, node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        out.insert(0, node.id)
    return out

def _literal_type(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):  return "bool"
        if isinstance(v, int):   return "int"
        if isinstance(v, float): return "double"
        if isinstance(v, str):   return "string"
        if v is None:            return "none"
    return None

def _name_or_attr_type(node: ast.AST) -> str | None:
    chain = _resolve_attr_chain(node)
    if not chain:
        return None
    leaf = chain[-1]
    # Match chrono.ChAxis_X or bare ChAxis_X
    if re.fullmatch(r"ChAxis_[A-Z]", leaf):
        return "ChAxis"
    # If user passed a material instance variable, we can't know statically;
    # if the var name suggests a material, be permissive.
    if re.search(r"material", leaf, flags=re.I):
        return "ChContactMaterial"
    return None

def _call_constructed_type(node: ast.Call) -> str | None:
    # Recognize constructed types by callee name (best-effort)
    chain = _resolve_attr_chain(node.func)
    name = chain[-1] if chain else ""
    if "ContactMaterial" in name:
        return "ChContactMaterial"
    return None

def _infer_arg_type(node: ast.AST) -> str:
    t = _literal_type(node)
    if t: return t
    if isinstance(node, (ast.Name, ast.Attribute)):
        t = _name_or_attr_type(node)
        if t: return t
        return "unknown"
    if isinstance(node, ast.Call):
        t = _call_constructed_type(node)
        return t or "unknown"
    # containers, expressions etc. default to unknown
    return "unknown"

def _arg_types_pos_kw(call: ast.Call) -> List[str]:
    types: List[str] = []
    # positional args
    for a in call.args:
        types.append(_infer_arg_type(a))
    # keyword args are also counted in arity; we infer type from value
    for kw in call.keywords or []:
        # Ignore **kwargs (kw.arg is None)
        if kw.arg is None:
            types.append("unknown")
        else:
            types.append(_infer_arg_type(kw.value))
    return types

# ---------- overload matching ----------

def _type_matches(expected: str, actual: str) -> bool:
    # normalize aliases
    if expected == "double" and actual in {"double", "int"}:
        return True
    if expected == "int" and actual == "int":
        return True
    if expected == "bool" and actual == "bool":
        return True
    if expected == "ChAxis" and actual == "ChAxis":
        return True
    if expected == "ChContactMaterial" and actual == "ChContactMaterial":
        return True
    # If we cannot infer actual statically, be strict and reject to avoid false passes
    if actual == "unknown":
        return False
    return expected == actual

def _args_fit_overload(given: List[str], overload: Dict[str, Any]) -> bool:
    exp: List[str] = overload.get("args", [])
    dflt: int = int(overload.get("defaults", 0))

    N = len(given)
    M = len(exp)

    # Default-aware arity check: you may omit up to 'defaults' trailing args
    if N > M or (M - N) > dflt:
        return False

    # Compare only the first N parameters by type
    for i in range(N):
        if not _type_matches(exp[i], given[i]):
            return False
    return True

def _pretty_overloads(name: str, ovs: List[Dict[str, Any]]) -> List[str]:
    out = []
    for ov in ovs:
        sig = ", ".join(ov.get("args", []))
        d  = ov.get("defaults", 0)
        suffix = (f"  [defaults={d}]" if d else "")
        out.append(f"{name}({sig}){suffix}")
    return out

# ---------- main validate ----------

def validate(code: str, allow: Dict[str, Any]) -> Tuple[bool, List[str]]:
    modules = allow["modules"]
    overloads = allow["overloads"]
    errors: List[str] = []

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, [f"SyntaxError: {e}"]

    # Enforce import style + collect alias->module mapping
    alias_to_mod: Dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if base.startswith("pychrono"):
                if base in PYCHRONO_ROOTS:
                    errors.append(f"Use 'import {base} as {PYCHRONO_ROOTS[base]}' (not 'from {base} import ...').")
                else:
                    errors.append(f"Disallowed import-from base: {base}")
            if any(x.name == "*" for x in getattr(n, "names", [])):
                errors.append(f"Star import banned: from {base} import *")

        if isinstance(n, ast.Import):
            for x in n.names:
                name, asname = x.name, x.asname
                if name in PYCHRONO_ROOTS:
                    want = PYCHRONO_ROOTS[name]
                    if asname != want:
                        errors.append(f"Import must be exactly: 'import {name} as {want}'")
                    alias_to_mod[want] = name
                elif name.startswith("pychrono") and name not in PYCHRONO_ROOTS:
                    errors.append(f"Disallowed pychrono submodule: {name}")

    # Attribute presence + legacy block
    def _is_allowed(mod: str, attr: str) -> bool:
        return attr in modules.get(mod, set())

    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id in LEGACY_BLOCKLIST:
            errors.append(f"Legacy symbol disallowed: {n.id}")

        if isinstance(n, ast.Attribute):
            chain = _resolve_attr_chain(n)
            if not chain:
                continue
            head = chain[0]
            # map alias to fully qualified pychrono module
            fq_mod = None
            for full, alias in PYCHRONO_ROOTS.items():
                if alias == head:
                    fq_mod = full
                    break
            if fq_mod and len(chain) >= 2:
                attr = chain[1]
                if attr in LEGACY_BLOCKLIST:
                    errors.append(f"Legacy symbol disallowed: {fq_mod}.{attr}")
                elif not _is_allowed(fq_mod, attr):
                    errors.append(f"Missing in 9.0.1 allowlist: {fq_mod}.{attr}")

    # Constructor / callable overload checks
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue

        chain = _resolve_attr_chain(n.func)
        if not chain:
            continue

        # require module alias as head (chrono/veh/irr/fea)
        head = chain[0]
        fq_mod = None
        for full, alias in PYCHRONO_ROOTS.items():
            if alias == head:
                fq_mod = full
                break
        if not fq_mod or len(chain) < 2:
            continue

        name = chain[1]
        fq = f"{fq_mod}.{name}"

        # If we have overloads for this callable, enforce them
        if fq in overloads:
            given_types = _arg_types_pos_kw(n)
            allowed_ov = overloads[fq]

            ok = any(_args_fit_overload(given_types, ov) for ov in allowed_ov)
            if not ok:
                pretty = _pretty_overloads(name, allowed_ov)
                errors.append(
                    "Constructor mismatch for "
                    f"{name}({', '.join(given_types)}) — allowed overloads:\n  - "
                    + "\n  - ".join(pretty)
                )

    return (len(errors) == 0), errors

# ---------- CLI ----------

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("codefile")
    ap.add_argument("--allowlist", default="allowlist.json")
    args = ap.parse_args()

    with open(args.codefile, "r", encoding="utf-8") as f:
        code = f.read()
    allow = load_allowlist(args.allowlist)
    ok, errs = validate(code, allow)
    if ok:
        print("[AST PASS]"); sys.exit(0)
    print("[AST FAIL]")
    for e in errs:
        print(" -", e)
    sys.exit(2)
