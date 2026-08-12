"""Backend-neutral request/response helpers for the plain HTTP routes.

The routes in `ztf_viewer/pages/{figure,lc_csv,favicon}.py` are registered with
`@app.server.route(...)` rather than as Dash callbacks, so they talk to the WSGI/ASGI backend
directly instead of through `dash.ctx`. Today that backend is Flask, and this module is the
*only* place allowed to `import flask` (enforced by a repo-wide grep / AST guard) so that a
later swap to Starlette (`aio-starlette-web`) touches this one file instead of every route.

Call sites should only use the names exported here, never `flask` directly.
"""

import flask

#: The current request, re-exported so call sites never import `flask` themselves.
request = flask.request


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
    """Serve a file from disk (e.g. the favicon)."""
    return flask.send_file(path, mimetype=mimetype)


def binary_response(data: bytes, mimetype: str, filename: str):
    """A binary attachment response, e.g. a rendered PNG/PDF figure."""
    return flask.Response(
        data,
        mimetype=mimetype,
        headers={"Content-disposition": f"attachment; filename={filename}"},
    )


def csv_response(text: str, filename: str):
    """A CSV attachment response."""
    return flask.Response(
        text,
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={filename}"},
    )


def error_response(body: str, status: int):
    """An error response, replacing the old `(body, status)` tuple pattern.

    No explicit mimetype is set so this matches Flask's own default (`text/html`) for a bare
    `(body, status)` return, keeping behaviour identical to what these routes did before.
    """
    return flask.Response(body, status=status)
