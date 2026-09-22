import logging
import pathlib

import dash
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from ztf_viewer.config import WEBSOCKET_HEARTBEAT_INTERVAL_MS
from ztf_viewer.social import social_meta_html

_STATIC_DIR = pathlib.Path(__file__).parent / "static"

# Where `_resolve_snad_name` leaves the name for `_Dash.interpolate_index` to find
SNAD_NAME_STATE = "snad_name"


class _StaticFilesNoCache(StaticFiles):
    """Serve static files with `Cache-Control: no-cache`, so browsers revalidate against the
    `ETag`/`Last-Modified` they already get instead of holding a stale copy."""

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


js9_css = [
    "/static/js9/js9support.css",
    "/static/js9/js9.css",
]

js9_js = [
    "/static/js/js9prefs.js",
    "/static/js9/js9support.min.js",
    "/static/js9/js9.min.js",
    "/static/js9/js9plugins.js",
]


class _Dash(dash.Dash):
    """Dash, plus the link preview tags of the page being served."""

    def interpolate_index(self, metas="", **kwargs):
        try:
            request = self.backend.request_adapter()
            # `request.context` is the request's `state`, where `_resolve_snad_name` below left
            # the object's name; the pathname alone cannot say whether it has one.
            social = social_meta_html(
                request.path, request.url, request.root, snad_name=getattr(request.context, SNAD_NAME_STATE, None)
            )
        except RuntimeError:
            # No request in context — `index()` called directly, as the tests do.
            social = ""
        return super().interpolate_index(metas="\n      ".join(filter(None, [metas, social])), **kwargs)


app = _Dash(
    __name__,
    external_stylesheets=js9_css,
    external_scripts=js9_js,
    health_endpoint="health",
    backend="fastapi",
    # Transport enabled; callbacks opt in individually via `websocket=True`.
    websocket_heartbeat_interval=WEBSOCKET_HEARTBEAT_INTERVAL_MS,
)
app.config.suppress_callback_exceptions = True


@app.server.middleware("http")
async def _resolve_snad_name(request, call_next):
    """Put the object's SNAD name, where it has one, on the request the index is built from."""
    # Imported inside: the catalogs pull in half the app, and this module is the bottom of it
    from ztf_viewer import routes
    from ztf_viewer.catalogs.snad.catalog import snad_name
    from ztf_viewer.util import DEFAULT_DR

    path = request.url.path
    match = routes.VIEWER.search(path) or routes.VIEWER_DEFAULT_DR.search(path)
    if request.method == "GET" and match:
        try:
            name = await snad_name(int(match["oid"]), match.groupdict().get("dr") or DEFAULT_DR)
        except Exception:
            # Broad on purpose: the lookup goes to an external API, and a preview is never
            # worth failing the page a reader asked for.
            logging.getLogger(__name__).warning("cannot resolve the SNAD name of %s", path, exc_info=True)
        else:
            setattr(request.state, SNAD_NAME_STATE, name)
    return await call_next(request)


# Dash serves `assets/` but not `static/`, which holds JS9 and the logo. Mount it at construction
# time: Dash appends a catch-all route later, and anything mounted after it never matches.
app.server.mount("/static", _StaticFilesNoCache(directory=str(_STATIC_DIR)), name="static")
