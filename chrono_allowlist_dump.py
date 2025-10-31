# chrono_allowlist_dump.py
"""
Build a symbol allow-list from your installed PyChrono 9.0.1, including
constructor overload signatures parsed from pybind11 docstrings.

Usage (one line):
  python -u chrono_allowlist_dump.py --out allowlist.json \
    --modules pychrono pychrono.irrlicht pychrono.vehicle pychrono.fea

Tips:
  - Use -u or PYTHONUNBUFFERED=1 so heartbeat prints show up immediately.
  - Adjust --hb-every and --hb-secs to change heartbeat frequency.
"""

import argparse, importlib, json, re, sys, time

PROTO_RE = re.compile(r"""
    ^\s*
    (?P<name>[A-Za-z_]\w*)
    \s*\((?P<args>.*)\)\s*$
""", re.VERBOSE)

def norm_tok(tok: str) -> str:
    t = tok.strip()
    t = re.sub(r"std::shared_ptr\s*<\s*([^>]+)\s*>", r"\1", t)
    t = t.replace("chrono::", "").replace("const ", "").replace("&", "").strip()
    if t in {"double", "float"}: return "double"
    if t in {"int", "size_t", "unsigned", "unsigned int"}: return "int"
    if t == "bool": return "bool"
    if t.startswith("ChContactMaterial"): return "ChContactMaterial"
    if t.startswith("ChAxis"): return "ChAxis"
    return t

def parse_overloads_from_doc(name: str, doc: str) -> list[list[str]]:
    overloads = []
    if not doc:
        return overloads
    for line in doc.splitlines():
        m = PROTO_RE.match(line.strip())
        if not m or m.group("name") != name:
            continue
        args = m.group("args").strip()
        if not args:
            overloads.append([])
            continue
        parts = [p.strip() for p in args.split(",")]
        overloads.append([norm_tok(p) for p in parts])
    return overloads

def dump(modules, hb_every: int, hb_secs: float, verbose: bool):
    start = time.monotonic()
    last_hb = start
    data_modules: dict[str, list[str]] = {}
    overloads: dict[str, list[list[str]]] = {}
    enums = set()
    total_syms = 0

    def heartbeat(phase: str, mname: str, idx: int | None = None, count: int | None = None):
        nonlocal last_hb
        now = time.monotonic()
        if (idx is not None and hb_every and idx % hb_every == 0) or (hb_secs and now - last_hb >= hb_secs):
            msg = f"[HB] {phase} module={mname}"
            if idx is not None and count is not None:
                msg += f" progress={idx}/{count}"
            msg += f" elapsed={now - start:.1f}s"
            print(msg, flush=True)
            last_hb = now

    for mname in modules:
        print(f"[INFO] Importing {mname} ...", flush=True)
        try:
            m = importlib.import_module(mname)
        except Exception as e:
            print(f"[WARN] Cannot import {mname}: {e}", file=sys.stderr, flush=True)
            data_modules[mname] = []
            continue

        symbols = sorted(dir(m))
        data_modules[mname] = symbols
        count = len(symbols)
        total_syms += count
        print(f"[INFO] {mname}: {count} symbols", flush=True)

        for i, sym in enumerate(symbols, 1):
            if verbose and i <= 5:
                print(f"[DBG]   scanning {mname}.{sym}", flush=True)
            heartbeat("scanning", mname, i, count)

            try:
                obj = getattr(m, sym)
            except Exception:
                continue

            # overloads
            try:
                doc = getattr(obj, "__doc__", "") or ""
            except Exception:
                doc = ""
            ols = parse_overloads_from_doc(sym, doc)
            if ols:
                overloads[f"{mname}.{sym}"] = ols

            # enum hint
            if re.match(r"ChAxis_[A-Z]$", sym):
                enums.add("ChAxis")

    elapsed = time.monotonic() - start
    print(f"[DONE] modules={len(modules)} total_symbols={total_syms} "
          f"overloads={len(overloads)} elapsed={elapsed:.1f}s", flush=True)

    return {"modules": data_modules, "overloads": overloads, "enums": sorted(enums)}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="allowlist.json")
    ap.add_argument("--modules", nargs="+", default=[
        "pychrono", "pychrono.irrlicht", "pychrono.vehicle", "pychrono.fea"
    ])
    ap.add_argument("--hb-every", type=int, default=200, help="print heartbeat every N symbols")
    ap.add_argument("--hb-secs", type=float, default=5.0, help="print heartbeat at least every N seconds")
    ap.add_argument("--verbose", action="store_true", help="print a few debug lines per module")
    args = ap.parse_args()

    payload = dump(args.modules, hb_every=args.hb_every, hb_secs=args.hb_secs, verbose=args.verbose)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
    print(f"[WROTE] {args.out} (modules + overloads + enums)", flush=True)
