"""防災ダッシュボード Flaskアプリケーション。"""
import json
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, g, jsonify, make_response, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config
from db.models import (
    delete_viewer_area,
    get_active_tsunami_warnings,
    get_active_typhoons,
    get_active_warnings,
    get_flood_forecasts,
    get_environment_info,
    get_heatstroke_alerts,
    get_latest_collection_log,
    get_recent_quakes,
    get_viewer_areas,
    get_volcano_alerts,
    upsert_viewer_area,
)
from scheduler.area_master import PREF_MASTER, get_pref_code_from_area_code

app = Flask(__name__)

_LEVEL_JA = {
    "advisory": "注意報",
    "warning": "警報",
    "special_warning": "特別警報",
}

@app.template_filter("level_ja")
def level_ja_filter(level: str | None) -> str:
    """英語の level 値を日本語表示に変換する。None や空文字は空文字を返す。"""
    if not level:
        return ""
    level_str = str(level).lower()
    return _LEVEL_JA.get(level_str, str(level))

app.secret_key = Config.SECRET_KEY
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

VIEWER_COOKIE = "viewer_id"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 365日

VALID_LIMITS = frozenset({20, 50, 100})
VALID_MIN_SCALES = frozenset({0, 10, 20, 30, 40, 50, 55, 60, 65, 70})

DEFAULT_LIMIT = 50
DEFAULT_MIN_SCALE = 0


def get_viewer_id() -> str:
    """リクエストからviewer_idを取得する。存在しない場合は新規UUID生成。"""
    return request.cookies.get(VIEWER_COOKIE) or str(uuid.uuid4())


def set_viewer_id_cookie(response, viewer_id: str):
    """レスポンスにviewer_id Cookieをセットする。"""
    expires = datetime.now() + timedelta(seconds=COOKIE_MAX_AGE)
    response.set_cookie(
        VIEWER_COOKIE,
        viewer_id,
        max_age=COOKIE_MAX_AGE,
        expires=expires,
        httponly=True,
        samesite="Lax",
    )
    return response


@app.before_request
def load_viewer_id() -> None:
    """リクエスト前にviewer_idをgに格納する。"""
    g.viewer_id = get_viewer_id()


def _make_response_with_cookie(template: str, **ctx):
    """テンプレートをレンダリングしCookieをセットしたレスポンスを返す。"""
    resp = make_response(render_template(template, **ctx))
    return set_viewer_id_cookie(resp, g.viewer_id)


def _get_last_updated() -> str | None:
    """最終収集時刻を取得する。"""
    logs = get_latest_collection_log()
    if not logs:
        return None
    ran_ats = [r.get("ran_at", "") for r in logs if r.get("ran_at")]
    return max(ran_ats) if ran_ats else None


def _enrich_warnings_with_pref(warnings: list[dict]) -> None:
    """警報リストに都道府県名・都道府県コードを付与する（インプレース）。"""
    for w in warnings:
        pref_code = get_pref_code_from_area_code(w.get("area_code"))
        w["pref_code"] = pref_code
        w["pref_name"] = PREF_MASTER.get(pref_code, "")
        if not w.get("area_name"):
            w["area_name"] = "全域"


# ─── ページルーティング ────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    """ダッシュボードトップ。登録地域のサマリー + 最新地震 + 現在警報 + 津波情報。"""
    viewer_areas = get_viewer_areas(g.viewer_id)
    quakes = get_recent_quakes(limit=10, min_scale=30)  # 震度3以上
    all_warnings = get_active_warnings()
    _enrich_warnings_with_pref(all_warnings)
    warnings = [w for w in all_warnings if (w.get("level") or "").lower() == "special_warning"]
    tsunami_warnings = get_active_tsunami_warnings()
    last_updated = _get_last_updated()
    return _make_response_with_cookie(
        "dashboard.html",
        viewer_areas=viewer_areas,
        quakes=quakes,
        warnings=warnings,
        all_warnings=all_warnings,
        tsunami_warnings=tsunami_warnings,
        last_updated=last_updated,
    )


@app.route("/quake")
def quake():
    """地震情報一覧ページ。クエリパラメータで最大震度・表示件数を絞り込み可能。"""
    limit = request.args.get("limit", default=DEFAULT_LIMIT, type=int)
    if limit not in VALID_LIMITS:
        limit = DEFAULT_LIMIT

    min_scale = request.args.get("min_scale", default=DEFAULT_MIN_SCALE, type=int)
    if min_scale not in VALID_MIN_SCALES:
        min_scale = DEFAULT_MIN_SCALE

    quakes = get_recent_quakes(limit=limit, min_scale=min_scale)
    last_updated = _get_last_updated()
    return _make_response_with_cookie(
        "quake.html",
        quakes=quakes,
        last_updated=last_updated,
        selected_limit=limit,
        selected_min_scale=min_scale,
    )


@app.route("/warning")
def warning():
    """警報・注意報一覧ページ。"""
    warnings = get_active_warnings()
    _enrich_warnings_with_pref(warnings)
    # pref_code の地理的順序（北から南）でソートしてからグループ化
    warnings.sort(key=lambda w: w.get("pref_code") or "999999")
    pref_groups: dict[str, list[dict]] = {}
    for w in warnings:
        key = w.get("pref_name") or w.get("area_code") or "不明"
        pref_groups.setdefault(key, []).append(w)
    last_updated = _get_last_updated()
    return _make_response_with_cookie("warning.html", pref_groups=pref_groups, last_updated=last_updated)


@app.route("/typhoon")
def typhoon():
    """台風情報ページ。"""
    typhoons = get_active_typhoons()
    for t in typhoons:
        raw_track = t.pop("track_json", None)
        t.pop("raw_json", None)
        try:
            parsed = json.loads(raw_track) if raw_track else []
            t["track"] = parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            t["track"] = []
    last_updated = _get_last_updated()
    return _make_response_with_cookie("typhoon.html", typhoons=typhoons, last_updated=last_updated)


@app.route("/heatstroke")
def heatstroke():
    """熱中症警戒アラートページ。"""
    alerts = get_heatstroke_alerts()
    last_updated = _get_last_updated()
    return _make_response_with_cookie("heatstroke.html", alerts=alerts, last_updated=last_updated)


@app.route("/volcano")
def volcano():
    """噴火警報ページ。"""
    alerts = get_volcano_alerts()
    last_updated = _get_last_updated()
    return _make_response_with_cookie("volcano.html", alerts=alerts, last_updated=last_updated)


@app.route("/river")
def river():
    """河川洪水予報ページ。"""
    forecasts = get_flood_forecasts()
    last_updated = _get_last_updated()
    return _make_response_with_cookie("river.html", forecasts=forecasts, last_updated=last_updated)


@app.route("/tsunami")
def tsunami():
    """津波警報・注意報ページ。"""
    tsunami_warnings = get_active_tsunami_warnings()
    last_updated = _get_last_updated()
    return _make_response_with_cookie(
        "tsunami.html", tsunami_warnings=tsunami_warnings, last_updated=last_updated
    )


@app.route("/environment")
def environment():
    """黄砂・紫外線情報ページ。"""
    env_info = get_environment_info()
    last_updated = _get_last_updated()
    return _make_response_with_cookie(
        "environment.html", env_info=env_info, last_updated=last_updated
    )


@app.route("/areas", methods=["GET", "POST", "DELETE"])
def areas():
    """地域設定ページ。GET: 一覧表示, POST: 地域追加, DELETE: 地域削除。"""
    if request.method == "POST":
        pref_code = request.form.get("pref_code", "").strip()
        area_code = request.form.get("area_code", pref_code).strip()
        name = PREF_MASTER.get(pref_code, pref_code)
        if pref_code:
            upsert_viewer_area(
                viewer_id=g.viewer_id,
                pref_code=pref_code,
                area_code=area_code,
                name=name,
            )
    elif request.method == "DELETE":
        area_code = request.args.get("area_code", "").strip()
        if area_code:
            delete_viewer_area(g.viewer_id, area_code)
        return jsonify({"ok": True})

    viewer_areas = get_viewer_areas(g.viewer_id)
    return _make_response_with_cookie(
        "areas.html",
        viewer_areas=viewer_areas,
        pref_master=PREF_MASTER,
    )


# ─── API エンドポイント ────────────────────────────────────────────────────────

@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """手動更新エンドポイント。collect_all を非同期で実行する。"""
    try:
        project_root = Path(__file__).parent.parent
        subprocess.Popen(
            [sys.executable, str(project_root / "scheduler" / "collect_all.py")],
            cwd=str(project_root),
        )
        return jsonify({"ok": True, "message": "収集を開始しました"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/status")
def api_status():
    """各ソースの最終収集時刻と成否を返す。"""
    logs = get_latest_collection_log()
    return jsonify({"ok": True, "sources": logs})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=Config.PORT, debug=Config.DEBUG)
