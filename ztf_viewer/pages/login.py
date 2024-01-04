import dash
from dash import Input, Output, State, dcc, html

from ztf_viewer.akb import akb
from ztf_viewer.app import app
from ztf_viewer.exceptions import UnAuthorized


def get_layout(*args, **kwargs):
    del args, kwargs

    return html.Div(
        [
            html.Br(),
            "Token:",
            dcc.Input(
                id="token",
                type="text",
                minLength=8,
                maxLength=40,
                n_submit=0,
            ),
            html.Div("", id="login-status"),
        ],
        id="login",
    )


@app.callback(Output("login-status", "children"), [Input("token", "n_submit")], [State("token", "value")])
def do_login(n_submit, token):
    try:
        username = akb.username(token)
    except UnAuthorized:
        return "Login failed: wrong token"
    if token:
        dash.callback_context.response.set_cookie(
            "akb_token", token, secure=True, samesite="Strict", max_age=31 * 86400
        )
    return ["You are authorised as ", html.B(username)]
