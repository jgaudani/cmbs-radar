"""Compare two api deployments endpoint by endpoint (same database), e.g.
before and after a change.

    uv run python scripts/compare_api.py http://127.0.0.1:8080 http://127.0.0.1:8081
"""

import json
import math
import re
import sys
import time
import urllib.request

A, B = sys.argv[1], sys.argv[2]
DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})T00:00:00Z$")


def get(base, path, method="GET"):
    for _ in range(60):
        try:
            with urllib.request.urlopen(urllib.request.Request(base + path, method=method), timeout=300) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            return {"_status": e.code, **json.load(e)}
        except Exception:
            time.sleep(1)
    raise SystemExit(f"{base} not up")


def norm(v):
    if isinstance(v, dict):
        return {k: norm(x) for k, x in v.items()}
    if isinstance(v, list):
        return [norm(x) for x in v]
    if isinstance(v, str) and (m := DATE.match(v)):
        return m.group(1)
    return v


def diff(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(a.keys() | b.keys()):
            yield from diff(a.get(k, "<missing>"), b.get(k, "<missing>"), f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            yield f"{path}: length {len(a)} vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            yield from diff(x, y, f"{path}[{i}]")
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        if not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9):
            yield f"{path}: {a} vs {b}"
    elif a != b:
        yield f"{path}: {a!r} vs {b!r}"


demo = "metro=nyc&type=OF&max_months=18&min_months=-120&class=gap_refi,distressed&limit=300"
paths = ["/api/meta", "/api/summary", "/api/summary?metro=nyc&type=OF", f"/api/opportunities?{demo}",
         "/api/opportunities?class=distressed,gap_refi,clean_refi&limit=300", "/api/opportunities?sort=maturity&limit=100",
         "/api/opportunities?q=park&sort=balance", f"/api/map?{demo}", "/api/map",
         "/api/opportunities?max_months=abc", "/api/opportunities/nope/1",
         "/api/scenario?rate_shift_bps=-50&class=distressed,gap_refi,clean_refi&limit=1000",
         f"/api/scenario?rate_shift_bps=-50&{demo}", "/api/backtest"]
ids = [o["id"] for o in get(A, f"/api/opportunities?{demo}")["opportunities"][:15]]
paths += [f"/api/opportunities/{i}" for i in ids]
bad = 0
for p in paths:
    g, y = norm(get(A, p)), norm(get(B, p))
    if p == "/api/meta":  # timestamp formats differ by language
        g.pop("scored_at", None), y.pop("scored_at", None)
    if p == "/api/backtest":
        g.pop("created_at", None), y.pop("created_at", None)
    ds = list(diff(g, y))
    print(f"{'OK  ' if not ds else 'DIFF'} {p}" + (f"  ({len(ds)} differences)" if ds else ""))
    for d in ds[:4]:
        print("     ", d)
    bad += bool(ds)
print(f"\n{len(paths) - bad}/{len(paths)} endpoints identical")
sys.exit(1 if bad else 0)
