"""Flask application: HTML pages plus a small JSON API.

Pages
    GET  /                    home: check-in charts (?range=week|month|6months|year) and past days
    GET  /today               redirect to today's entry
    GET  /<YYYY-MM-DD>        edit one day

API (also the hook for scripts and future features)
    GET  /api/entries         all saved entries, newest first
    GET  /api/entries/<date>  one entry (blank if not yet written)
    PUT  /api/entries/<date>  validate and save one entry
    POST /api/entries/<date>/images  upload one image (multipart field "file"), returns its file name
    GET  /images/<date>/<name> serve an uploaded image
    POST /api/shutdown        stop the server (needs header X-Journal: 1)
"""

from __future__ import annotations

import os
import signal
import threading
from datetime import date, timedelta

from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, url_for

from .insights import DEFAULT_RANGE, RANGES, RANGES_BY_ID, build_charts, window_start
from .palette import PALETTE
from .schema import SCALE_MAX, SECTIONS
from .storage import IMAGE_NAME, Store, parse_date


MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _day_or_404(value: str) -> date:
    try:
        return parse_date(value)
    except ValueError:
        abort(404)


def create_app(data_dir: str | os.PathLike[str] | None = None) -> Flask:
    """Application factory. ``data_dir`` defaults to ``$JOURNAL_DATA_DIR`` or ``./data``."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    store = Store(data_dir or os.environ.get("JOURNAL_DATA_DIR", "data"))
    app.extensions["journal_store"] = store

    @app.context_processor
    def inject_palette():
        return {"palette": PALETTE}

    @app.get("/")
    def home():
        rng = RANGES_BY_ID.get(request.args.get("range", ""), RANGES_BY_ID[DEFAULT_RANGE])
        today = date.today()
        start = window_start(rng, today)
        entries = list(store.entries(start, today))
        return render_template(
            "home.html",
            ranges=RANGES,
            rng=rng,
            start=start,
            today=today,
            charts=build_charts(entries, rng, today),
            entries=entries,
            today_saved=any(e["date"] == today.isoformat() for e in entries),
        )

    @app.get("/today")
    def today():
        return redirect(url_for("entry_page", day=date.today().isoformat()))

    @app.get("/<day>")
    def entry_page(day: str):
        d = _day_or_404(day)
        return render_template(
            "entry.html",
            entry=store.load(d),
            day=d,
            prev_day=d - timedelta(days=1),
            next_day=d + timedelta(days=1),
            is_today=d == date.today(),
            sections=SECTIONS,
            scale=range(1, SCALE_MAX + 1),
        )

    @app.get("/api/entries")
    def api_list():
        return jsonify(list(store.entries()))

    @app.get("/api/entries/<day>")
    def api_get(day: str):
        return jsonify(store.load(_day_or_404(day)))

    @app.put("/api/entries/<day>")
    def api_put(day: str):
        d = _day_or_404(day)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            abort(400, "expected a JSON object")
        return jsonify(store.save(d, body))

    @app.post("/api/entries/<day>/images")
    def api_upload_image(day: str):
        d = _day_or_404(day)
        upload = request.files.get("file")
        if upload is None:
            abort(400, "missing file")
        try:
            return jsonify(file=store.save_image(d, upload.read())), 201
        except ValueError:
            abort(415, "use a JPEG, PNG, GIF or WebP image")

    @app.get("/images/<day>/<name>")
    def image(day: str, name: str):
        d = _day_or_404(day)
        if not IMAGE_NAME.fullmatch(name):
            abort(404)
        resp = send_from_directory(store.image_dir(d).resolve(), name)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    @app.post("/api/shutdown")
    def api_shutdown():
        # Custom header forces a CORS preflight, so other websites cannot kill the app.
        if request.headers.get("X-Journal") != "1":
            abort(403)
        # Delay so this response reaches the browser before the server stops.
        threading.Timer(0.3, os.kill, (os.getpid(), signal.SIGINT)).start()
        return jsonify(ok=True)

    return app


def main() -> None:
    """Console entry point: ``uv run journal``."""
    create_app().run(host="127.0.0.1", port=5000)
