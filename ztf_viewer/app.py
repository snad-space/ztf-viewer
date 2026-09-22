import pathlib

import dash
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from ztf_viewer.config import WEBSOCKET_HEARTBEAT_INTERVAL_MS
from ztf_viewer.social import social_meta_html

_STATIC_DIR = pathlib.Path(__file__).parent / "static"


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
    """Dash, plus the link preview tags of the page being served.

    Dash renders one index for every URL, so the social tags cannot be `meta_tags` given once at
    construction: they are added here, where the request is still around to say which page the
    index is standing in for.
    """

    def interpolate_index(self, metas="", **kwargs):
        try:
            request = self.backend.request_adapter()
            social = social_meta_html(request.path, request.url, request.root)
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

# Dash serves `assets/` but not `static/`, which holds JS9 and the logo. Mount it at construction
# time: Dash appends a catch-all route later, and anything mounted after it never matches.
app.server.mount("/static", _StaticFilesNoCache(directory=str(_STATIC_DIR)), name="static")
