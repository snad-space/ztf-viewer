import dash
import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate

from app import app
from secret import is_user_token_valid


def get_layout(pathname):
    return html.Div(
        [
            html.Br(),
            'Token:',
            dcc.Input(
                id='token',
                type='text',
                minLength=16,
                maxLength=16,
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
    if n_submit == 0 or token is None:
        raise PreventUpdate
    if not is_user_token_valid(token):
        return 'Login failed: wrong token'
    dash.callback_context.response.set_cookie('login_token', token, secure=True, samesite='Strict', max_age=31 * 86400)
    return 'Login successful'
