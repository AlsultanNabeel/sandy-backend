"""The browser's routes, behind the `browser` switch (404 without it, like no such screen).

  GET    /api/stop          {stopped}: the emergency stop (`features/stop_all`)
  POST   /api/stop          {stopped: true}: every task and browser job stops now
  DELETE /api/stop          {stopped: false}: it all goes on again
  GET    /api/browser/sites                       {sites: [{site, level, signed_in, session_at}]}
  PATCH  /api/browser/sites/<site>                {level: read | fill | submit}: {site}
  POST   /api/browser/sites/<site>/session        {cookies, storage}: his sign-in, sealed: {site}
  DELETE /api/browser/sites/<site>/session        «طلّعها»: the sign-in forgotten: {site}
  GET    /api/browser/jobs                        {jobs: [{id, site, status, created_at}]}: his open fills
  GET    /api/browser/jobs/<id>/live              {url}: «متصفح ساندي», to watch only
  POST   /api/browser/jobs/<id>/takeover          {url}: «خليني أكمّل أنا»: the agent stops, the view drives

Steel's view has no protection of its own: it reaches only the fill's owner (another account's
fill is 404) and is never logged or traced.

Every route is the caller's own tenant.
"""

from __future__ import annotations

import functools
import logging

from flask import jsonify, request

from app.api.auth_handlers import require_tenant
from app.brain import lang
from app.features import browser_job, browser_sites, stop_all

logger = logging.getLogger(__name__)


def _switched(view):
    """Runs in the caller's tenant, only for an account with the switch on."""
    @functools.wraps(view)
    def wrapped(*args, claims, **kwargs):
        from app.brain import tools_browser
        if not tools_browser.offered(claims.get("user_id") or ""):
            return jsonify({"error": "not_found"}), 404
        return view(*args, claims=claims, **kwargs)
    return require_tenant(wrapped)


def register_browser_api(app) -> None:
    @app.route("/api/stop", methods=["GET"])
    @_switched
    def stop_state(claims):
        return jsonify({"stopped": stop_all.stopped(claims["user_id"])})

    @app.route("/api/stop", methods=["POST"])
    @_switched
    def stop_now(claims):
        if not stop_all.stop(claims["user_id"]):
            return jsonify({"error": "unavailable", "message": lang.say("stop_failed")}), 503
        return jsonify({"stopped": True})

    @app.route("/api/stop", methods=["DELETE"])
    @_switched
    def stop_end(claims):
        if not stop_all.resume(claims["user_id"]):
            return jsonify({"error": "unavailable", "message": lang.say("stop_failed")}), 503
        return jsonify({"stopped": False})

    @app.route("/api/browser/sites", methods=["GET"])
    @_switched
    def browser_sites_list(claims):
        return jsonify({"sites": browser_sites.sites()})

    @app.route("/api/browser/sites/<site>", methods=["PATCH"])
    @_switched
    def browser_site_level(site, claims):
        body = request.get_json(silent=True) or {}
        try:
            kept = browser_sites.set_level(site, str(body.get("level") or ""))
        except ValueError:
            return jsonify({"error": "bad_level", "message": lang.say("browser_bad_level")}), 400
        if not kept:
            return jsonify({"error": "unavailable", "message": lang.say("stop_failed")}), 503
        return jsonify({"site": browser_sites.shown(site)})

    @app.route("/api/browser/sites/<site>/session", methods=["POST"])
    @_switched
    def browser_site_session(site, claims):
        from app.features import web_page
        name = browser_sites.site_of(site)
        if not name or web_page.blocked_site(name):
            return jsonify({"error": "blocked", "message": lang.say("page_blocked", site=name)}), 400
        try:
            kept = browser_sites.save_session(name, request.get_json(silent=True))
        except ValueError:
            return jsonify({"error": "bad_session", "message": lang.say("browser_bad_session")}), 400
        if not kept:
            return jsonify({"error": "unavailable", "message": lang.say("browser_not_kept")}), 503
        return jsonify({"site": browser_sites.shown(name)})

    @app.route("/api/browser/sites/<site>/session", methods=["DELETE"])
    @_switched
    def browser_site_sign_out(site, claims):
        if not browser_sites.sign_out(site):
            return jsonify({"error": "unavailable", "message": lang.say("stop_failed")}), 503
        return jsonify({"site": browser_sites.shown(site)})

    @app.route("/api/browser/jobs", methods=["GET"])
    @_switched
    def browser_jobs(claims):
        return jsonify({"jobs": browser_job.open_jobs()})

    @app.route("/api/browser/jobs/<job_id>/live", methods=["GET"])
    @_switched
    def browser_job_live(job_id, claims):
        row = browser_job.get(job_id) or {}
        url = browser_job.live_url(job_id, control=row.get("status") == browser_job.HANDED)
        if not url:
            return jsonify({"error": "not_found", "message": lang.say("fill_gone")}), 404
        return jsonify({"url": url, "control": row.get("status") == browser_job.HANDED})

    @app.route("/api/browser/jobs/<job_id>/takeover", methods=["POST"])
    @_switched
    def browser_job_takeover(job_id, claims):
        if not browser_job.take_over(job_id):
            return jsonify({"error": "not_found", "message": lang.say("fill_gone")}), 404
        return jsonify({"url": browser_job.live_url(job_id, control=True), "control": True})
