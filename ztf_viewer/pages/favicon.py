from ztf_viewer.app import app
from ztf_viewer.web import file_response


@app.server.api_route("/favicon.ico")
def favicon():
    return file_response("static/img/logo.svg", mimetype="image/svg+xml")
