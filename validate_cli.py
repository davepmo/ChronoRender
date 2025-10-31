"""CLI wrapper to validate Python against PyChrono 9.0.1 AST rules."""
import sys, argparse
from chrono_ast_gate_v2 import load_allowlist, validate
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--allowlist", default="allowlist.json")
    ap.add_argument("codefile", help="Path to code or '-' for stdin")
    args = ap.parse_args()
    code = sys.stdin.read() if args.codefile == '-' else open(args.codefile,'r',encoding='utf-8').read()
    allow = load_allowlist(args.allowlist)
    ok, errs = validate(code, allow)
    if ok: print("[AST PASS]"); sys.exit(0)
    print("[AST FAIL]"); [print(" -",e) for e in errs]; sys.exit(2)
if __name__ == "__main__": main()
