# chrono_ctor_harvester_core_v4.py
# Extract PyChrono constructor overloads by parsing help() text robustly (SWIG style).
# Fixes:
#  - Accepts leading '|' and box-drawing chars in pydoc output
#  - Supports wrapped __init__(...) signatures across multiple lines
# Outputs:
#  - allowlist.json        {"modules": {...}, "overloads": {...}, "enums": [...]}
#  - harvester_report.txt  per-class status

import re, os, sys, json, time, inspect, importlib, pydoc
from typing import List, Dict

MODULES = ["pychrono.core", "pychrono.vehicle", "pychrono.irrlicht", "pychrono.fea"]

# strip leading pipes/box characters + spaces
LEADING_UI = re.compile(r'^[\s\|\u2500-\u257F]+')  # unicode box range
INIT_HEAD = re.compile(r'^__init__\s*\(')

def norm_tok(tok: str) -> str:
    t = tok.strip()
    # simplify shared_ptr and qualifiers
    t = re.sub(r"std::shared_ptr\s*<\s*([^>]+)\s*>", r"\1", t)
    t = t.replace("chrono::", "").replace("const ", "").replace("&", "").strip()
    if t in {"double","float"}: return "double"
    if t in {"int","unsigned","unsigned int","size_t"}: return "int"
    if t == "bool": return "bool"
    if t.startswith("ChContactMaterial"): return "ChContactMaterial"
    if t.startswith("ChAxis"): return "ChAxis"
    return t

def split_args(args: str) -> List[str]:
    out, buf, depth = [], [], 0
    for ch in args:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth-1)
        elif ch == "," and depth == 0:
            tok = "".join(buf).strip()
            if tok: out.append(tok)
            buf = []
            continue
        buf.append(ch)
    last = "".join(buf).strip()
    if last: out.append(last)
    return out

def parse_init_inside(inside: str) -> List[str]:
    # inside like: 'ChBodyEasyCylinder self, chrono::ChAxis direction, double radius, ... material=0'
    parts = split_args(inside)
    types = []
    for p in parts:
        if p == "self" or p.endswith(" self"): continue
        left = p.split("=",1)[0].strip()
        if " " in left:
            left = left.split(" ",1)[0]
        types.append(norm_tok(left))
    return types

def harvest_from_help(cls) -> List[List[str]]:
    try:
        doc = pydoc.render_doc(cls)
    except Exception:
        return []
    lines = doc.splitlines()
    overloads: List[List[str]] = []

    i = 0
    while i < len(lines):
        raw = lines[i]
        s = LEADING_UI.sub("", raw)  # drop leading UI chars
        if INIT_HEAD.match(s):
            # accumulate until we see a closing ')' in this or subsequent lines
            buf = [s]
            # Fast path: if this line has ')', we’re done
            if ")" not in s:
                j = i + 1
                while j < len(lines):
                    nxt = LEADING_UI.sub("", lines[j])
                    # stop at next section header or method name
                    if INIT_HEAD.match(nxt) or nxt.strip().endswith(":") or nxt.strip()=="":
                        break
                    buf.append(nxt)
                    if ")" in nxt:
                        j += 1
                        break
                    j += 1
                i = j - 1  # adjust loop index
            sig = " ".join(buf)
            # extract between first '(' and matching ')'
            try:
                inside = sig[sig.index("(")+1 : sig.rindex(")")]
                types = parse_init_inside(inside)
                if types:
                    if types not in overloads:
                        overloads.append(types)
            except Exception:
                pass
        i += 1
    return overloads

def iter_classes(module_name: str):
    try:
        m = importlib.import_module(module_name)
    except Exception as e:
        print(f"[WARN] cannot import {module_name}: {e}", file=sys.stderr)
        return
    for attr in sorted(dir(m)):
        try:
            obj = getattr(m, attr)
        except Exception:
            continue
        if inspect.isclass(obj):
            mod = getattr(obj, "__module__", "") or ""
            if not mod.startswith("pychrono"):
                continue
            yield module_name, attr, obj

def main():
    import pychrono as chrono
    enums = set()
    # enum probe in core namespace too
    try:
        if any(getattr(chrono, n, None) is not None for n in ("ChAxis_X","ChAxis_Y","ChAxis_Z")):
            enums.add("ChAxis")
    except Exception:
        pass
    try:
        import pychrono.core as chcore
        if any(getattr(chcore, n, None) is not None for n in ("ChAxis_X","ChAxis_Y","ChAxis_Z")):
            enums.add("ChAxis")
    except Exception:
        pass

    modules_map: Dict[str, set] = {}
    overloads_map: Dict[str, List[List[str]]] = {}
    report = []

    total = 0
    with_ols = 0

    for mname in MODULES:
        print(f"[INFO] scanning {mname} ...")
        modules_map.setdefault(mname, set())
        for _, cname, cls in iter_classes(mname):
            total += 1
            modules_map[mname].add(cname)
            ols = harvest_from_help(cls)
            if ols:
                with_ols += 1
                key = f"{mname}.{cname}"
                overloads_map[key] = ols
                report.append(f"[OK] {key}  sigs={len(ols)}  ex={ols[:2]}")
            else:
                report.append(f"[--] {mname}.{cname}  (no ctor overloads)")

    allow = {
        "modules": {k: sorted(v) for k, v in modules_map.items()},
        "overloads": overloads_map,
        "enums": sorted(enums),
    }
    with open("allowlist.json","w",encoding="utf-8") as f:
        json.dump(allow, f, indent=2, sort_keys=True)
    with open("harvester_report.txt","w",encoding="utf-8") as f:
        f.write("\n".join(report))

    print(f"[DONE] classes={total} with_overloads={with_ols}")
    print("[WROTE] allowlist.json, harvester_report.txt")

if __name__ == "__main__":
    main()
