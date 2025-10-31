# chrono_validator_v3.py
# Overload-aware AST validator for PyChrono 9.0.1.
# - Loads allowlist.json that includes "overloads": { "pychrono.core.Class": [[arg types ...], ...] }
# - Validates constructor calls for known classes (e.g., chrono.ChBodyEasyCylinder(...))
# - Enforces module/class allowlist; rejects unknown legacy API (v7/v8) names.

import ast, json, re, os
from typing import Any, Dict, List, Optional, Tuple

# ---------- configuration ----------
ALLOWLIST_FILE = os.environ.get("CHRONO_ALLOWLIST_FILE", "allowlist.json")
# We accept these import styles in user code:
#   import pychrono as chrono
#   import pychrono.core as chrono
#   from pychrono import core as chrono   (rare)
#   (We collapse them so "chrono" is the alias we validate against.)
ACCEPTED_ALIASES = {"chrono"}      # the alias the user should call (chrono.X)
ACCEPTED_ROOTS  = {"pychrono", "pychrono.core"}  # what alias "chrono" may point to

# Enum reconcilers for quick type inference
ENUM_TYPES = {"ChAxis"}  # keep in sync with allowlist["enums"]

# Map of "fully qualified or unqualified" -> [[type1, type2, ...], ...]
CtorOverloads = {}  # filled at load

# Map alias -> root module ok?
AliasRoots: Dict[str, str] = {}   # e.g., {"chrono": "pychrono.core"}

# ---------- helpers ----------

def load_allowlist(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def normalize_class_key(mod_class: str) -> str:
    # Prefer fully qualified "pychrono.core.Class"; fall back to "pychrono.Class"
    return mod_class

def add_key_variants(store: Dict[str, List[List[str]]], fqcn: str, sigs: List[List[str]]):
    # Keep both fully-qualified and shorter aliases for convenience.
    store[fqcn] = sigs
    if fqcn.startswith("pychrono.core."):
        short = "pychrono." + fqcn.split(".", 2)[-1]
        store.setdefault(short, sigs)
    # Also raw class name (last hop) for internal mapping lookups (not exposed to user)
    cname = fqcn.split(".")[-1]
    store.setdefault(cname, sigs)

# Very light type inference from AST node -> one of: "double","int","bool","ChAxis","ChContactMaterial","unknown"
def infer_type(node: ast.AST) -> str:
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):  return "bool"
        if isinstance(v, int):   return "int"
        if isinstance(v, float): return "double"
        return "unknown"
    if isinstance(node, ast.NameConstant):  # py<3.8 legacy
        if node.value in (True, False): return "bool"
        return "unknown"
    if isinstance(node, ast.Name):
        # Could be enum like ChAxis_Z assigned elsewhere; treat plain names as unknown.
        return "unknown"
    if isinstance(node, ast.Attribute):
        # chrono.ChAxis_Z -> enum
        # Any *.ChAxis_* counts as ChAxis
        attr = node.attr
        if attr.startswith("ChAxis_"):  # e.g., chrono.ChAxis_Z
            return "ChAxis"
        # Materials are usually constructed via calls; a bare attr is unknown
        return "unknown"
    if isinstance(node, ast.Call):
        # constructor call (e.g., chrono.ChContactMaterialSMC())
        # try to recognize material classes by name
        target = node.func
        if isinstance(target, ast.Attribute):
            name = target.attr  # e.g., ChContactMaterialSMC
        elif isinstance(target, ast.Name):
            name = target.id
        else:
            name = ""
        if name.startswith("ChContactMaterial"):
            return "ChContactMaterial"
        return "unknown"
    # default:
    return "unknown"

def match_overload(arg_types: List[str], overloads: List[List[str]]) -> bool:
    # Simple positional matching: lengths equal and every arg type matches exactly, with basic numeric coercion.
    for sig in overloads:
        if len(sig) != len(arg_types):
            continue
        ok = True
        for got, want in zip(arg_types, sig):
            if want == "double" and got in ("double","int"):
                continue
            if want == "int" and got == "int":
                continue
            if want == "bool" and got == "bool":
                continue
            if want == "ChAxis" and got == "ChAxis":
                continue
            if want == "ChContactMaterial" and got == "ChContactMaterial":
                continue
            ok = False
            break
        if ok:
            return True
    return False

def qualname_for_ctor(func: ast.AST) -> Optional[str]:
    # We allow patterns like chrono.ChBodyEasyCylinder, (alias).ChBodyEasyCylinder
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        alias = func.value.id
        if alias in ACCEPTED_ALIASES:
            return func.attr  # raw class name; we’ll resolve later
    return None

class ChronoVisitor(ast.NodeVisitor):
    def __init__(self):
        self.errors: List[str] = []
        self.found_alias: Optional[str] = None
        self.imported: Dict[str, str] = {}  # alias -> root

    def visit_Import(self, node: ast.Import) -> None:
        # import pychrono as chrono
        for n in node.names:
            if n.name in ACCEPTED_ROOTS:
                alias = n.asname or n.name.split(".")[0]
                self.imported[alias] = n.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # from pychrono import core as chrono
        mod = node.module or ""
        if mod.startswith("pychrono"):
            for n in node.names:
                alias = n.asname or n.name
                self.imported[alias] = mod

    def visit_Call(self, node: ast.Call) -> None:
        # Validate constructor calls against overloads
        ctor_name = qualname_for_ctor(node.func)
        if ctor_name:
            # Resolve overload list for this class
            sigs = None
            for k in (f"pychrono.core.{ctor_name}", f"pychrono.{ctor_name}", ctor_name):
                if k in CtorOverloads:
                    sigs = CtorOverloads[k]; break
            if not sigs:
                self.errors.append(
                    f"Use of '{ctor_name}': no ctor overload metadata found (did you regenerate allowlist.json with overloads?)."
                )
            else:
                # Infer arg types
                arg_types = [infer_type(a) for a in node.args]
                if not match_overload(arg_types, sigs):
                    self.errors.append(
                        f"Constructor mismatch for {ctor_name}({', '.join(arg_types)}). "
                        f"Allowed overloads: {sigs}"
                    )
        self.generic_visit(node)

def validate_python(src: str) -> Tuple[bool, List[str]]:
    # Load allowlist (with overloads)
    allow = load_allowlist(ALLOWLIST_FILE)
    overloads = allow.get("overloads", {})
    # Fill global table with key variants
    CtorOverloads.clear()
    for fq, sigs in overloads.items():
        add_key_variants(CtorOverloads, fq, sigs)

    # Parse AST and visit
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return False, [f"SyntaxError: {e}"]

    v = ChronoVisitor()
    v.visit(tree)

    # Basic ban on legacy API symbols (if you kept a denylist, add it here)
    # Example: reject any attribute names that are known v7/v8-only
    LEGACY_BANNED = {"ChBodyEasyCylinderAUX", "ChLinkEngine"}  # example placeholders
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr in LEGACY_BANNED:
                v.errors.append(f"Legacy API symbol detected: {node.attr}")

    return (len(v.errors) == 0), v.errors
