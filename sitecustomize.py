"""Runtime guard to loudly block legacy symbols at attribute access time."""
import sys, types
LEGACY = {"ChBodyAuxRef","ChLinkEngine","ChSharedPtr","ChSystemSMC7","ChSystemNSC7","ChVectorDynamic","ChMatrix33","ChShared"}
def _wrap(mod):
    class Guard(types.ModuleType):
        def __getattr__(self, name):
            if name in LEGACY:
                raise AttributeError(f"[Chrono 9.0.1 strict] Legacy symbol blocked: {name}")
            return getattr(mod, name)
    g = Guard(mod.__name__); g.__dict__.update(mod.__dict__); return g
for m in ("pychrono","pychrono.vehicle","pychrono.irrlicht"):
    try: sys.modules[m] = _wrap(__import__(m, fromlist=['*']))
    except Exception: pass
