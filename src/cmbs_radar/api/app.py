"""HTTP API and demo UI over ingest and scoring data (FastAPI)."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from importlib import resources

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .brief import PROMPT_VERSION, Generator, MissingCredentialsError, RefusedError
from .service import BadParam, Filter, NotFound, Service, map_points, opportunity, summarize

log = logging.getLogger("api")


class _UIFiles(StaticFiles):
    """index.html must be revalidated so a deploy is picked up at once; the
    hashed assets it references are immutable and cache forever."""

    async def get_response(self, path: str, scope):
        resp = await super().get_response(path, scope)
        if path.startswith("assets/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            resp.headers["Cache-Control"] = "no-cache"
        return resp


def create_app(svc: Service, briefer: Generator | None) -> FastAPI:
    app = FastAPI(title="CMBS Radar", docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.monotonic()
        resp = await call_next(request)
        if request.url.path != "/healthz":
            log.info("http method=%s path=%s status=%d took=%dms", request.method, request.url.path, resp.status_code,
                     1000 * (time.monotonic() - start))
        return resp

    @app.exception_handler(BadParam)
    async def bad_param(_: Request, e: BadParam):
        return JSONResponse({"error": str(e)}, status_code=400)

    @app.exception_handler(NotFound)
    async def not_found(_: Request, e: NotFound):
        return JSONResponse({"error": str(e)}, status_code=404)

    @app.get("/healthz")
    def healthz():
        return "ok"

    @app.get("/api/meta")
    def meta():
        return svc.meta()

    @app.get("/api/summary")
    def summary(request: Request):
        f = Filter.parse(dict(request.query_params))
        return summarize(f.apply(svc.snap.rows), svc.snap.data_as_of)

    @app.get("/api/opportunities")
    def opportunities(request: Request):
        f = Filter.parse(dict(request.query_params))
        rows = f.apply(svc.snap.rows)
        return {"total": len(rows), "run_id": svc.snap.run_id, "opportunities": [opportunity(r) for r in rows[:f.limit]]}

    @app.get("/api/map")
    def map_(request: Request):
        return map_points(Filter.parse(dict(request.query_params)).apply(svc.snap.rows))

    @app.get("/api/opportunities/{trust}/{asset}")
    def detail(trust: str, asset: str):
        return svc.detail(trust, asset)

    @app.post("/api/opportunities/{trust}/{asset}/brief")
    def brief(trust: str, asset: str, refresh: str = ""):
        if refresh != "1" and (b := svc.cached_brief(trust, asset)) is not None:
            return b
        facts = svc.detail(trust, asset)  # 404 if unknown
        if briefer is None:
            return JSONResponse({"error": "briefs are disabled"}, status_code=503)
        try:
            text, model = briefer.write(facts)
        except MissingCredentialsError:
            return JSONResponse({"error": "briefs need Claude credentials: set ANTHROPIC_API_KEY for the api server"}, status_code=503)
        except RefusedError as e:
            return JSONResponse({"error": str(e)}, status_code=502)
        except Exception as e:
            log.exception("brief loan=%s/%s", trust, asset)
            return JSONResponse({"error": f"claude: {e}"}, status_code=502)
        b = {"trust_cik": trust, "asset_number": asset, "run_id": svc.snap.run_id, "prompt_version": PROMPT_VERSION,
             "model": model, "brief": text, "created_at": datetime.now(timezone.utc), "cached": False}
        try:
            svc.save_brief(b, facts)
        except Exception:
            log.exception("caching brief")  # still return it
        return b

    @app.get("/api/scenario")
    def scenario(request: Request):
        q = dict(request.query_params)
        try:
            bps = float(q.get("rate_shift_bps", ""))
        except ValueError:
            bps = float("nan")
        if not -500 <= bps <= 500:
            raise BadParam("rate_shift_bps must be a number in [-500, 500], e.g. -50")
        return svc.scenario(bps, Filter.parse(q))

    @app.get("/api/backtest")
    def backtest():
        return svc.backtest()

    # The React UI (frontend/) is built into web/; serve it when present.
    web = resources.files("cmbs_radar.api").joinpath("web")
    if web.joinpath("index.html").is_file():
        app.mount("/", _UIFiles(directory=str(web), html=True), name="web")
    else:
        @app.get("/", response_class=HTMLResponse)
        def ui_not_built():
            return ("<p>The UI isn't built. Run <code>cd frontend && npm install && npm run build</code>, "
                    "then restart the api. The API itself is up: see <a href='/api/docs'>/api/docs</a>.</p>")
    return app
