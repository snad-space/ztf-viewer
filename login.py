import dash
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate

from akb import akb
from app import app
from util import UnAuthorized


def get_layout(pathname):
    return html.Div(
        [
            html.Br(),
            'Token:',
            dcc.Input(
                id='token',
                type='text',
                minLength=8,
                maxLength=40,
                n_submit=0,
            ),
            html.Div('', id='login-status')
        ],
        id='login',
    )


@app.callback(
    Output('login-status', 'children'),
    [Input('token', 'n_submit')],
    state=[State('token', 'value')]
)
def do_login(n_submit, token):
    try:
        username = akb.username(token)
    except UnAuthorized:
        return 'Login failed: wrong token'
    if token:
        dash.callback_context.response.set_cookie('akb_token', token, secure=True, samesite='Strict',
                                                  max_age=31 * 86400)
    return ['You are authorised as ', html.B(username)]
