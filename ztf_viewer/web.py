"""Backend-neutral request/response helpers for the plain HTTP routes.

The routes in `ztf_viewer/pages/{figure,lc_csv,favicon}.py` are registered with
`@app.server.route(...)` rather than as Dash callbacks, so they talk to the WSGI/ASGI backend
directly instead of through `dash.ctx`. Today that backend is Starlette (via FastAPI), and this
module is the *only* place allowed to `import flask` (enforced by a repo-wide grep / AST guard).

Call sites should only use the names exported here, never `flask` or `starlette` directly.
"""

import pathlib

import flask
from fastapi.responses import FileResponse, HTMLResponse, Response

#: The current request, re-exported so call sites never import `flask` themselves.
#: Starlette has no ambient request equivalent -- this is the one name in this module that
#: still needs a real request object threaded through as a handler argument at every call site.
request = flask.request

_PACKAGE_ROOT = pathlib.Path(__file__).parent


class QueryArgs:
    """Read-only, backend-neutral view over a request's query-string arguments."""

    def __init__(self, args):
        self._args = args

    def get(self, key, default=None):
        return self._args.get(key, default)

    def getlist(self, key):
        return list(self._args.getlist(key))


def query_args(request) -> QueryArgs:  # noqa: F811 - shadows the module-level `request` on purpose
    """Return the query-string arguments of `request` as a `QueryArgs`."""
    return QueryArgs(request.args)


def request_body(request) -> bytes:
    """Return the raw body bytes of `request`."""
    return request.get_data(cache=False)


def file_response(path, mimetype):
    """Serve a file from disk (e.g. the favicon).

    `path` may be relative (as `favicon.py` passes it); resolve it against the package
    directory rather than the process CWD, matching Flask's `send_file` app-root resolution.
    """
    path = pathlib.Path(path)
    if not path.is_absolute():
        path = _PACKAGE_ROOT / path
    return FileResponse(path, media_type=mimetype)


def binary_response(data: bytes, mimetype: str, filename: str):
    """A binary attachment response, e.g. a rendered PNG/PDF figure."""
    return Response(
        data,
        media_type=mimetype,
        headers={"Content-disposition": f"attachment; filename={filename}"},
    )


def csv_response(text: str, filename: str):
    """A CSV attachment response."""
    return Response(
        text,
        media_type="text/csv",
        headers={"Content-disposition": f"attachment; filename={filename}"},
    )


def error_response(body: str, status: int):
    """An error response, replacing the old `(body, status)` tuple pattern.

    Explicit `text/html` so this matches Flask's own default for a bare `(body, status)`
    return, keeping behaviour identical to what these routes did before.
    """
    return HTMLResponse(body, status_code=status)
