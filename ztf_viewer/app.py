import pathlib

import dash
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

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


app = dash.Dash(
    __name__,
    external_stylesheets=js9_css,
    external_scripts=js9_js,
    health_endpoint="/health",
    backend="fastapi",
)
app.config.suppress_callback_exceptions = True

# Dash serves `assets/` but not `static/`, which holds JS9 and the logo. Mount it at construction
# time: Dash appends a catch-all route later, and anything mounted after it never matches.
app.server.mount("/static", _StaticFilesNoCache(directory=str(_STATIC_DIR)), name="static")
