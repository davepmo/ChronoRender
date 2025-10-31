"""AST validator (v2) for PyChrono 9.0.1-only code, now including pychrono.fea."""
import ast, json, argparse, sys
PYCHRONO_ROOTS = {
    "pychrono": "chrono",
    "pychrono.vehicle": "veh",
    "pychrono.irrlicht": "irr",
    "pychrono.fea": "fea",
}
LEGACY_BLOCKLIST = {"ChBodyAuxRef","ChLinkEngine","ChSharedPtr","ChSystemSMC7","ChSystemNSC7","ChVectorDynamic","ChMatrix33","ChShared"}
def load_allowlist(path):
    with open(path,"r",encoding="utf-8") as f: return {k:set(v) for k,v in json.load(f).items()}
def _resolve_attr_chain(node):
    out=[]; 
    while isinstance(node, ast.Attribute): out.insert(0,node.attr); node=node.value
    if isinstance(node, ast.Name): out.insert(0,node.id)
    return out
def validate(code, allow):
    errors=[]
    try: tree=ast.parse(code)
    except SyntaxError as e: return False,[f"SyntaxError: {e}"]
    alias_to_mod={}
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            base=n.module or ""
            if base.startswith("pychrono") and base in PYCHRONO_ROOTS:
                errors.append(f"Use 'import {base} as {PYCHRONO_ROOTS[base]}' not 'from {base} import ...'")
            if any(x.name=="*" for x in getattr(n,'names',[])):
                errors.append(f"Star import banned: from {base} import *")
            if base.startswith("pychrono") and base not in PYCHRONO_ROOTS:
                errors.append(f"Disallowed import-from base: {base}")
        if isinstance(n, ast.Import):
            for x in n.names:
                name,asname=x.name,x.asname
                if name in PYCHRONO_ROOTS:
                    want=PYCHRONO_ROOTS[name]
                    if asname!=want: errors.append(f"Import must be: 'import {name} as {want}'")
                    alias_to_mod[want]=name
                elif name.startswith("pychrono") and name not in PYCHRONO_ROOTS:
                    errors.append(f"Disallowed pychrono submodule: {name}")
    def is_allowed(mod, attr): return attr in allow.get(mod,set())
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id in LEGACY_BLOCKLIST: errors.append(f"Legacy symbol disallowed: {n.id}")
        if isinstance(n, ast.Attribute):
            chain=_resolve_attr_chain(n)
            if not chain: continue
            head=chain[0]; mod=None
            for k,a in PYCHRONO_ROOTS.items():
                if a==head: mod=k; break
            if mod and len(chain)>=2:
                attr=chain[1]
                if attr in LEGACY_BLOCKLIST: errors.append(f"Legacy symbol disallowed: {mod}.{attr}")
                elif not is_allowed(mod, attr): errors.append(f"Missing in 9.0.1: {mod}.{attr}")
        if isinstance(n, ast.Call):
            chain=_resolve_attr_chain(n.func)
            if chain:
                head=chain[0]; mod=None
                for k,a in PYCHRONO_ROOTS.items():
                    if a==head: mod=k; break
                if mod and len(chain)>=2:
                    attr=chain[1]
                    if attr not in allow.get(mod,set()): errors.append(f"Call to unknown: {mod}.{attr}(...)")
    return len(errors)==0, errors
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("codefile")
    ap.add_argument("--allowlist", default="allowlist.json")
    args = ap.parse_args()
    with open(args.codefile, "r", encoding="utf-8") as f: code=f.read()
    allow = load_allowlist(args.allowlist)
    ok, errs = validate(code, allow)
    if ok: print("[AST PASS]"); sys.exit(0)
    print("[AST FAIL]"); [print(" -",e) for e in errs]; sys.exit(2)
