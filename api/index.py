from __future__ import annotations

import os
import sys
from pathlib import Path

from flask import Flask, jsonify, redirect, request, send_from_directory, session

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auth import SESSION_FLAG, SESSION_USER, protect_flask_app  # noqa: E402
from services.filters import args_from_request, build_meta, dimension_options  # noqa: E402
from services.store import get_deals, matrix_available  # noqa: E402
from services import insights, widgets  # noqa: E402

PUBLIC_DIR = ROOT / "public"
# Hidden admin tabs. On Vercel they stay closed until ADMIN_ACCESS_KEY is set;
# locally the old dev key still works for convenience.
ADMIN_ACCESS_KEY = os.environ.get("ADMIN_ACCESS_KEY") or (None if os.environ.get("VERCEL") else "dev-admin-key")

app = Flask(__name__, static_folder=None)
protect_flask_app(app)


def _json(data, status: int = 200):
    resp = jsonify(data)
    resp.status_code = status
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _require_admin(a: dict):
    if not ADMIN_ACCESS_KEY or a.get("access") != ADMIN_ACCESS_KEY:
        return _json({"error": "forbidden"}, 403)
    return None


@app.get("/api/me")
def api_me():
    return _json({"ok": True, "user": session.get(SESSION_USER)})


@app.get("/api/meta")
def api_meta():
    df = get_deals()
    return _json(build_meta(df, matrix=matrix_available()))


@app.get("/api/dimensions")
def api_dimensions():
    df = get_deals()
    a = args_from_request(request)
    return _json(dimension_options(df, a))


@app.get("/api/deals/kpi")
def api_deals_kpi():
    return _json(widgets.dashboard_kpi(get_deals(), args_from_request(request)))


@app.get("/api/deals/monthly-counts")
def api_deals_monthly_counts():
    return _json(widgets.dashboard_monthly_counts(get_deals(), args_from_request(request)))


@app.get("/api/deals/monthly-avg")
def api_deals_monthly_avg():
    return _json(widgets.dashboard_monthly_avg(get_deals(), args_from_request(request)))


@app.get("/api/deals/budget-buckets")
def api_deals_budget_buckets():
    return _json(widgets.dashboard_budget_buckets(get_deals(), args_from_request(request)))


@app.get("/api/deals/monthly-sqm")
def api_deals_monthly_sqm():
    return _json(widgets.dashboard_monthly_sqm(get_deals(), args_from_request(request)))


@app.errorhandler(Exception)
def api_error(err):  # pragma: no cover - safety net
    from werkzeug.exceptions import HTTPException

    if isinstance(err, HTTPException):
        return err
    app.logger.exception("Unhandled error on %s", request.path)
    if request.path.startswith("/api/"):
        return _json({"error": "Ошибка на сервере, попробуйте изменить фильтры"}, 500)
    return ("Internal Server Error", 500)


@app.get("/api/pace")
def api_pace():
    return _json(insights.sales_pace(get_deals(), args_from_request(request)))


@app.get("/api/price-dynamics")
def api_price_dynamics():
    return _json(insights.price_dynamics(get_deals(), args_from_request(request)))


@app.get("/api/mortgage")
def api_mortgage():
    return _json(insights.mortgage_breakdown(get_deals(), args_from_request(request)))


@app.get("/api/deals/top-complexes")
def api_deals_top():
    return _json(widgets.dashboard_top_complexes(get_deals(), args_from_request(request)))


@app.get("/api/complexes/city-counts")
def api_complexes_city():
    return _json(widgets.complexes_city_counts(get_deals(), args_from_request(request)))


@app.get("/api/complexes/monthly")
def api_complexes_monthly():
    return _json(widgets.complexes_monthly(get_deals(), args_from_request(request)))


@app.get("/api/compare")
def api_compare():
    return _json(widgets.compare_data(get_deals(), args_from_request(request)))


@app.get("/api/heatmap")
def api_heatmap():
    return _json(widgets.heatmap_data(get_deals(), args_from_request(request)))


@app.get("/api/heatmap/details")
def api_heatmap_details():
    return _json(widgets.heatmap_cell_details(get_deals(), args_from_request(request)))


@app.get("/api/euler")
def api_euler():
    return _json(widgets.euler_data(get_deals(), args_from_request(request)))


@app.get("/api/egrz")
def api_egrz():
    return _json(widgets.egrz_data(args_from_request(request)))


@app.get("/api/lot-growth")
def api_lot_growth():
    a = args_from_request(request)
    denied = _require_admin(a)
    if denied:
        return denied
    return _json(widgets.lot_growth_data(get_deals(), a))


@app.get("/api/project-growth")
def api_project_growth():
    a = args_from_request(request)
    denied = _require_admin(a)
    if denied:
        return denied
    return _json(widgets.project_growth_data(get_deals(), a))


def _public_file(*parts: str) -> Path:
    return PUBLIC_DIR.joinpath(*parts)


@app.get("/")
@app.get("/index.html")
def index_page():
    if not session.get(SESSION_FLAG):
        return redirect("/login")
    index_path = _public_file("index.html")
    if not index_path.exists():
        return ("Dashboard shell not found", 500)
    return send_from_directory(index_path.parent, index_path.name)


@app.get("/css/<path:filename>")
def css_files(filename: str):
    return send_from_directory(_public_file("css"), filename)


@app.get("/js/<path:filename>")
def js_files(filename: str):
    if not session.get(SESSION_FLAG):
        return jsonify({"error": "unauthorized"}), 401
    return send_from_directory(_public_file("js"), filename)


@app.get("/favicon.ico")
def favicon():
    icon = PUBLIC_DIR / "favicon.ico"
    if icon.exists():
        return send_from_directory(PUBLIC_DIR, "favicon.ico")
    return ("", 204)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8050"))
    app.run(host="127.0.0.1", port=port, debug=True)
