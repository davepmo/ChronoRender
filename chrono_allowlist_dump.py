# chrono_allowlist_dump.py
"""
Build a symbol allow-list from your installed PyChrono 9.0.1, including
constructor overload signatures parsed from pybind11 docstrings.

Usage (recommended):
  python chrono_allowlist_dump.py --out allowlist.json \
    --modules pychrono pychrono.irrlicht pychrono.vehicle pychrono.fea
"""
import argparse, importlib, json, re, sys, inspect

PROTO_RE = re.compile(r"""
    ^\s*                                    # leading
    (?P<name>[A-Za-z_]\w*)                  # function/ctor name
    \s*\((?P<args>.*)\)\s*$                 # (arg list)
""", re.VERBOSE)

# Normalize C++/pybind-ish tokens to gate-types
def norm_tok(tok: str) -> str:
    t = tok.strip()
    # strip namespaces / shared_ptrs
    t = re.sub(r"std::shared_ptr\s*<\s*([^>]+)\s*>", r"\1", t)
    t = t.replace("chrono::", "")
    t = t.replace("const ", "").replace("&", "").strip()
    # common maps
    if t in {"double", "float"}: return "double"
    if t in {"int", "size_t", "unsigned", "unsigned int"}: return "int"
    if t in {"bool"}: return "bool"
    if t.startswith("ChContactMaterial"): return "ChContactMaterial"
    if t.startswith("ChAxis"): return "ChAxis"
    # Fall back to raw (e.g., class type)
    return t

def parse_overloads_from_doc(name: str, doc: str) -> list[list[str]]:
    """
    Look for lines like:
      ChBodyEasyCylinder(ChAxis,double,double,double,bool,bool, std::shared_ptr< chrono::ChContactMaterial >)
    Return list of arg-type lists.
    """
    overloads = []
    if not doc:
        return overloads
    for line in doc.splitlines():
        m = PROTO_RE.match(line.strip())
        if not m:
            continue
        if m.group("name") != name:
            continue
        args = m.group("args").strip()
        if args == "":
            overloads.append([])
            continue
        # split by commas at top-level (docs are simple here)
        parts = [p.strip() for p in args.split(",")]
        overloads.append([norm_tok(p) for p in parts])
    return overloads

def dump(modules):
    data = {}
    overloads = {}   # fully-qualified like "pychrono.ChBodyEasyCylinder" -> [[types...], ...]
    enums = set()    # e.g., "ChAxis"

    for mname in modules:
        try:
            m = importlib.import_module(mname)
        except Exception as e:
            print(f"[WARN] Cannot import {mname}: {e}", file=sys.stderr)
            data[mname] = []
            continue

        symbols = sorted(dir(m))
        data[mname] = symbols

        for sym in symbols:
            fq = f"{mname}.{sym}"
            obj = getattr(m, sym, None)
            if obj is None:
                continue

            # Try to capture overloads from doc
            doc = getattr(obj, "__doc__", "") or ""
            tsig = getattr(obj, "__text_signature__", None)
            if tsig and isinstance(tsig, str):
                # e.g. (self, axis: ChAxis, r: float, h: float, density: float)
                # Not always present; keep doc parsing primary.
                pass

            ols = parse_overloads_from_doc(sym, doc)
            if ols:
                overloads[fq] = ols

            # Record enum families by name hints (best-effort)
            # If module exposes enum attrs like ChAxis_X, treat base "ChAxis" as enum type
            if re.match(r"ChAxis_[A-Z]$", sym):
                enums.add("ChAxis")

    return {"modules": data, "overloads": overloads, "enums": sorted(enums)}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="allowlist.json")
    ap.add_argument("--modules", nargs="+", default=[
        "pychrono", "pychrono.irrlicht", "pychrono.vehicle", "pychrono.fea"
    ])
    args = ap.parse_args()

    payload = dump(args.modules)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    print(f"[WROTE] {args.out}  (modules + overloads + enums)")
