from flask import send_file

from ztf_viewer.app import app


@app.server.route("/favicon.ico")
def favicon():
    return send_file("static/img/logo.svg", mimetype="image/svg+xml")
