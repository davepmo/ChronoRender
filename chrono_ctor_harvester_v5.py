# chrono_ctor_harvester_core_v5.py
# Extract PyChrono constructor overloads by parsing help() text (SWIG style),
# and record TRAILING defaulted parameters per overload.
#
# Outputs:
#  - allowlist.json        {"modules": {...}, "overloads": {...}, "enums": [...]}
#  - harvester_report.txt  per-class status
#
# Changes from v4:
#  - parse and store {"args":[...], "defaults": <int>} for each ctor
#  - stronger type normalization (std::shared_ptr<...>, chrono::, spaces)
#  - robust multi-line __init__ aggregation
#  - keeps the same modules list

import re, os, sys, json, time, inspect, importlib, pydoc
from typing import List, Dict, Tuple

MODULES = ["pychrono.core", "pychrono.vehicle", "pychrono.irrlicht", "pychrono.fea"]

# strip leading pipes/box characters + spaces
LEADING_UI = re.compile(r'^[\s\|\u2500-\u257F]+')  # unicode box range
INIT_HEAD = re.compile(r'^__init__\s*\(')

def norm_type(tok: str) -> str:
    """Normalize a C++/SWIG type token into our compact allowlist type."""
    t = tok.strip()

    # Collapse shared_ptr
    t = re.sub(r"std::shared_ptr\s*<\s*([^>]+)\s*>", r"\1", t)

    # Remove refs/const/chrono namespaces and extra spaces
    t = t.replace("&", " ").replace("const ", " ")
    t = t.replace("chrono::", " ").replace("::", " ")
    t = re.sub(r"\s+", " ", t).strip()

    # Keep only the left-most type-ish identifier if a name follows
    # e.g., "double radius" -> "double"
    t = t.split(" ", 1)[0]

    # Canonical scalars
    if t in {"double", "float"}:
        return "double"
    if t in {"int", "unsigned", "unsigned int", "size_t"}:
        return "int"
    if t == "bool":
        return "bool"

    # Chrono classes we want to coalesce
    if t.startswith("ChContactMaterial"):
        return "ChContactMaterial"
    if t.startswith("ChAxis"):
        return "ChAxis"

    return t

def split_args(arglist: str) -> List[str]:
    """Split a raw '(...)' arglist by commas, ignoring commas inside <...>."""
    out, buf, depth = [], [], 0
    for ch in arglist:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            tok = "".join(buf).strip()
            if tok:
                out.append(tok)
            buf = []
            continue
        buf.append(ch)
    last = "".join(buf).strip()
    if last:
        out.append(last)
    return out

def parse_init_inside(inside: str) -> List[Tuple[str, bool]]:
    """
    Parse the signature inside the parentheses of __init__(...).

    Returns a list of tuples: [(normalized_type, has_default: bool), ...]
    where 'has_default' is True if the parameter had '=...' in the signature.
    """
    # inside like: 'ChBodyEasyCylinder self, chrono::ChAxis direction, double radius, ... material=0'
    parts = split_args(inside)
    typed: List[Tuple[str, bool]] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue

        # Skip 'self'
        if p == "self" or p.endswith(" self"):
            continue

        # Separate default if present
        left, has_default = (p, False)
        if "=" in p:
            left = p.split("=", 1)[0].strip()
            has_default = True

        # Take only the type token (drop parameter name)
        # e.g., "double radius" -> "double"
        if " " in left:
            left = left.split(" ", 1)[0]

        typed.append((norm_type(left), has_default))
    return typed

def harvest_from_help(cls) -> List[Dict[str, object]]:
    """
    Return a list of overload dicts for class 'cls':
    [
      { "args": ["ChAxis","double","double","double","bool","bool","ChContactMaterial"], "defaults": 3 },
      { "args": ["ChAxis","double","double","double","ChContactMaterial"], "defaults": 0 }
    ]
    """
    try:
        doc = pydoc.render_doc(cls)
    except Exception:
        return []
    lines = doc.splitlines()

    overloads: List[Dict[str, object]] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        s = LEADING_UI.sub("", raw)  # drop leading UI chars
        if INIT_HEAD.match(s):
            # accumulate until we see a closing ')' (possibly across multiple lines)
            buf = [s]
            if ")" not in s:
                j = i + 1
                while j < len(lines):
                    nxt = LEADING_UI.sub("", lines[j])
                    # Heuristic break if new section/method starts
                    if INIT_HEAD.match(nxt) or nxt.strip().endswith(":"):
                        break
                    buf.append(nxt)
                    if ")" in nxt:
                        j += 1
                        break
                    j += 1
                i = j - 1  # consume extra lines
            sig = " ".join(buf)

            # Extract between first '(' and last ')'
            try:
                inside = sig[sig.index("(")+1 : sig.rindex(")")]
            except ValueError:
                i += 1
                continue

            typed = parse_init_inside(inside)
            if not typed:
                i += 1
                continue

            # Count TRAILING defaults
            defaults = 0
            for t, has_def in reversed(typed):
                if has_def:
                    defaults += 1
                else:
                    break

            args = [t for t, _ in typed]

            # Deduplicate logically (by args + defaults)
            rec = {"args": args, "defaults": defaults}
            if rec not in overloads:
                overloads.append(rec)
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

    # Probe enums (ChAxis) in either alias
    enums = set()
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
    overloads_map: Dict[str, List[Dict[str, object]]] = {}
    report = []

    total = 0
    with_ols = 0

    for mname in MODULES:
        print(f"[INFO] scanning {mname} ...")
        modules_map.setdefault(mname, set())
        for _, cname, cls in iter_classes(mname):
            total += 1
            modules_map[mname].add(cname)
            overs = harvest_from_help(cls)
            key = f"{mname}.{cname}"
            if overs:
                with_ols += 1
                overloads_map[key] = overs
                # brief example for report
                ex = overs[:2]
                report.append(f"[OK] {key}  sigs={len(overs)}  ex={ex}")
            else:
                report.append(f"[--] {key}  (no ctor overloads)")

    allow = {
        "modules": {k: sorted(v) for k, v in modules_map.items()},
        "overloads": overloads_map,
        "enums": sorted(enums),
    }
    with open("allowlist.json", "w", encoding="utf-8") as f:
        json.dump(allow, f, indent=2, sort_keys=True)
    with open("harvester_report.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    print(f"[DONE] classes={total} with_overloads={with_ols}")
    print("[WROTE] allowlist.json, harvester_report.txt")

if __name__ == "__main__":
    main()
