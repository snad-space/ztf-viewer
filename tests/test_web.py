"""Unit tests for the Starlette-backed helpers in `ztf_viewer/web.py`.

Each helper is exercised directly by constructing its response and driving it through a
throwaway Starlette app with `fastapi.testclient.TestClient`, independent of Dash/FastAPI
route registration (which is not ported to this backend until a later PR in the stack).
"""

import pathlib

import pytest
from fastapi.applications import Starlette
from fastapi.datastructures import QueryParams
from fastapi.testclient import TestClient
from starlette.routing import Route

import ztf_viewer
from ztf_viewer.web import (
    QueryArgs,
    binary_response,
    csv_response,
    error_response,
    file_response,
    query_args,
)

_PACKAGE_ROOT = pathlib.Path(ztf_viewer.__file__).parent


def _client_for(handler):
    """A `TestClient` for a single-route Starlette app wrapping `handler`."""
    app = Starlette(routes=[Route("/", handler, methods=["GET", "POST"])])
    return TestClient(app)


def test_file_response_resolves_relative_path_against_package_root():
    """`favicon.py` passes a *relative* path; it must resolve against the package directory,
    not the process CWD, or it 404s depending on where the process happens to be started from.
    """

    def handler(request):
        return file_response("static/img/logo.svg", mimetype="image/svg+xml")

    response = _client_for(handler).get("/")

    assert response.status_code == 200
    assert "image/svg+xml" in response.headers.get("content-type", "")
    assert response.content == (_PACKAGE_ROOT / "static" / "img" / "logo.svg").read_bytes()


def test_file_response_accepts_absolute_path():
    def handler(request):
        return file_response(str(_PACKAGE_ROOT / "static" / "img" / "logo.svg"), mimetype="image/svg+xml")

    response = _client_for(handler).get("/")

    assert response.status_code == 200
    assert response.content == (_PACKAGE_ROOT / "static" / "img" / "logo.svg").read_bytes()


@pytest.mark.parametrize("mimetype", ["image/png", "application/pdf"])
def test_binary_response_content_type_is_exact(mimetype):
    """`tests/test_golden_http.py` asserts these content types exactly, with no charset suffix."""

    def handler(request):
        return binary_response(b"\x00\x01\x02", mimetype=mimetype, filename="thing.bin")

    response = _client_for(handler).get("/")

    assert response.status_code == 200
    assert response.headers["content-type"] == mimetype
    assert response.headers["content-disposition"] == "attachment; filename=thing.bin"
    assert response.content == b"\x00\x01\x02"


def test_csv_response_content_type_and_disposition():
    def handler(request):
        return csv_response("a,b\n1,2\n", filename="data.csv")

    response = _client_for(handler).get("/")

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert response.headers["content-disposition"] == "attachment; filename=data.csv"
    assert response.text == "a,b\n1,2\n"


def test_error_response_defaults_to_html():
    """Flask's bare `(body, status)` return is `text/html; charset=utf-8`; keep it that way."""

    def handler(request):
        return error_response("not found", 404)

    response = _client_for(handler).get("/")

    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    assert response.text == "not found"


def test_query_args_wraps_any_get_getlist_multidict():
    """`QueryArgs` itself is already backend-neutral: it only needs `.get`/`.getlist`, which
    Starlette's `request.query_params` offers directly -- confirmed here against a real
    `QueryParams` instance rather than Flask's `request.args`.
    """
    args = QueryArgs(QueryParams("a=1&b=2&b=3"))

    assert args.get("a") == "1"
    assert args.getlist("b") == ["2", "3"]
    assert args.get("missing", "default") == "default"


def test_query_args_function_reads_starlette_query_params():
    """`query_args(request)` reads `request.query_params`, the attribute a real Starlette/FastAPI
    `Request` exposes.
    """

    class _FakeRequest:
        query_params = QueryParams("a=1&b=2&b=3")

    wrapped = query_args(_FakeRequest())

    assert wrapped.get("a") == "1"
    assert wrapped.getlist("b") == ["2", "3"]
