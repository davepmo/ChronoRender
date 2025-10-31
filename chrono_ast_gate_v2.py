# chrono_ast_gate_v2.py
"""
AST validator (v2.1) for PyChrono 9.0.1-only code, with overload checking.
- Enforces strict imports:
    import pychrono as chrono
    import pychrono.vehicle as veh
    import pychrono.irrlicht as irr
    import pychrono.fea as fea
- Bans star-imports and ImportFrom on pychrono modules.
- Validates attribute chains against allowlist modules.
- Validates constructor calls by arg COUNT & TYPE against parsed overloads.
"""
import ast, json, argparse, sys, re
from typing import Any

PYCHRONO_ROOTS = {
    "pychrono": "chrono",
    "pychrono.vehicle": "veh",
    "pychrono.irrlicht": "irr",
    "pychrono.fea": "fea",
}

LEGACY_BLOCKLIST = {
    "ChBodyAuxRef", "ChLinkEngine", "ChSharedPtr", "ChSystemSMC7",
    "ChSystemNSC7", "ChVectorDynamic", "ChMatrix33", "ChShared",
}

def load_allowlist(path):
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    # old format compatibility:
    if "modules" in raw:
        modules = {k: set(v) for k, v in raw["modules"].items()}
        overloads = {k: v for k, v in raw.get("overloads", {}).items()}
        enums = set(raw.get("enums", []))
    else:
        modules = {k: set(v) for k, v in raw.items()}
        overloads, enums = {}, set()
    return {"modules": modules, "overloads": overloads, "enums": enums}

def _resolve_attr_chain(node):
    out=[]
    while isinstance(node, ast.Attribute):
        out.insert(0, node.attr); node=node.value
    if isinstance(node, ast.Name):
        out.insert(0, node.id)
    return out

def _literal_type(node: ast.AST) -> str | None:
    # map Python literal -> gate type
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool): return "bool"
        if isinstance(v, (int,)): return "int"
        if isinstance(v, (float,)): return "double"
        if isinstance(v, str): return "string"
        if v is None: return "none"
    return None

def _call_type(node: ast.Call) -> str | None:
    # Recognize known constructed types by name (best-effort)
    chain = _resolve_attr_chain(node.func)
    if chain:
        name = chain[-1]
        if "ContactMaterial" in name: return "ChContactMaterial"
    return None

def _name_or_attr_type(node: ast.AST, alias_to_mod: dict) -> str | None:
    # Map enum constants to their base type (e.g., ChAxis_X -> ChAxis)
    chain = _resolve_attr_chain(node)
    if not chain: return None
    # Accept both chrono.ChAxis_X and bare ChAxis_X (hard to be sure statically)
    leaf = chain[-1]
    if re.match(r"ChAxis_[A-Z]$", leaf):
        return "ChAxis"
    return None

def _arg_types(args: list[ast.AST], alias_to_mod: dict) -> list[str]:
    types = []
    for a in args:
        t = _literal_type(a)
        if t is None and isinstance(a, ast.Name | ast.Attribute):
            t = _name_or_attr_type(a, alias_to_mod)
        if t is None and isinstance(a, ast.Call):
            t = _call_type(a)
        types.append(t or "unknown")
    return types

def _types_compatible(given: list[str], want: list[str]) -> bool:
    if len(given) != len(want): return False
    for g, w in zip(given, want):
        if w == "double" and g in {"double","int"}:  # ints acceptable for double
            continue
        if w == "int" and g == "int":
            continue
        if w == "bool" and g == "bool":
            continue
        if w == "ChAxis" and g == "ChAxis":
            continue
        if w == "ChContactMaterial" and g == "ChContactMaterial":
            continue
        # allow unknown if we cannot infer but keep it strict? choose strict:
        if g == "unknown":
            return False
        if g != w:
            return False
    return True

def validate(code: str, allow):
    modules = allow["modules"]
    overloads = allow["overloads"]
    errors = []

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, [f"SyntaxError: {e}"]

    # Enforce imports and collect alias map
    alias_to_mod = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if base.startswith("pychrono") and base in PYCHRONO_ROOTS:
                errors.append(f"Use 'import {base} as {PYCHRONO_ROOTS[base]}' not 'from {base} import ...'")
            if any(x.name == "*" for x in getattr(n, "names", [])):
                errors.append(f"Star import banned: from {base} import *")
            if base.startswith("pychrono") and base not in PYCHRONO_ROOTS:
                errors.append(f"Disallowed import-from base: {base}")

        if isinstance(n, ast.Import):
            for x in n.names:
                name, asname = x.name, x.asname
                if name in PYCHRONO_ROOTS:
                    want = PYCHRONO_ROOTS[name]
                    if asname != want:
                        errors.append(f"Import must be: 'import {name} as {want}'")
                    alias_to_mod[want] = name
                elif name.startswith("pychrono") and name not in PYCHRONO_ROOTS:
                    errors.append(f"Disallowed pychrono submodule: {name}")

    # Attribute presence + legacy
    def is_allowed(mod: str, attr: str) -> bool:
        return attr in modules.get(mod, set())

    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id in LEGACY_BLOCKLIST:
            errors.append(f"Legacy symbol disallowed: {n.id}")

        if isinstance(n, ast.Attribute):
            chain = _resolve_attr_chain(n)
            if not chain: continue
            head = chain[0]
            # reverse alias -> module name
            mod = None
            for k, alias in PYCHRONO_ROOTS.items():
                if alias == head:
                    mod = k; break
            if mod and len(chain) >= 2:
                attr = chain[1]
                if attr in LEGACY_BLOCKLIST:
                    errors.append(f"Legacy symbol disallowed: {mod}.{attr}")
                elif not is_allowed(mod, attr):
                    errors.append(f"Missing in 9.0.1: {mod}.{attr}")

    # Overload/arg checks on calls
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        chain = _resolve_attr_chain(n.func)
        if not chain: continue
        head = chain[0]
        mod = None
        for k, alias in PYCHRONO_ROOTS.items():
            if alias == head:
                mod = k; break
        if not mod or len(chain) < 2:
            continue
        attr = chain[1]
        fq = f"{mod}.{attr}"

        # If we have recorded overloads for this callable, enforce them
        if fq in overloads:
            given_types = _arg_types(n.args, alias_to_mod)
            allowed = overloads[fq]
            ok_one = any(_types_compatible(given_types, want) for want in allowed)
            if not ok_one:
                # Pretty print the allowed prototypes
                pretty = [f"{attr}({', '.join(w)})" for w in allowed]
                errors.append(
                    f"Call does not match 9.0.1 overloads for {fq}: got ({', '.join(given_types)}); "
                    f"allowed: {pretty}"
                )

    return len(errors) == 0, errors

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
    print("[AST FAIL]"); [print(" -", e) for e in errs]; sys.exit(2)
