"""Build a symbol allow-list from your installed PyChrono 9.0.1."""
import argparse, importlib, json, sys
def dump(mods):
    data = {}
    for mname in mods:
        try:
            m = importlib.import_module(mname)
            data[mname] = sorted(dir(m))
            print(f"[OK] {mname}: {len(data[mname])} symbols")
        except Exception as e:
            print(f"[WARN] {mname}: {e}", file=sys.stderr)
            data[mname] = []
    return data
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="allowlist.json")
    ap.add_argument("--modules", nargs="+", default=["pychrono","pychrono.irrlicht","pychrono.vehicle","pychrono.fea"]) 
    args = ap.parse_args()
    data = dump(args.modules)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    print(f"[WROTE] {args.out}")
