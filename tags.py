import dash_core_components as dcc
import dash_html_components as html
import flask
import re
from dash.dependencies import Input, Output, State, MATCH, ALL
from dash.exceptions import PreventUpdate

from akb import akb
from app import app
from config import is_user_token_valid


def get_layout(pathname):
    return html.Div([
        html.H1('Anomaly knowledge database tags', id='header-tags'),
        html.Div(
            [
                html.Div(id='tags-list'),
                html.Br(),
                html.Div(
                    [
                        html.Button(
                            'Save',
                            n_clicks=0,
                            id='tags-list-save-button',
                        ),
                        html.Div(id='tags-list-save-status', style={'display': 'inline-block'}),
                    ],
                    id='tags-list-save',
                ),
                html.Br(),
                html.Div(
                    [
                        html.Button(
                            'Reset',
                            n_clicks=0,
                            id='tags-list-reset-button',
                        ),
                    ],
                    id='tags-list-reset',
                ),
            ],
        ),
        html.Div(id='tags-placeholder', style={'display': 'none'}),
    ])


@app.callback(
    Output('tags-list', 'children'),
    [
        Input('url', 'pathname'),
        Input('tags-list-save-status', 'children'),
        Input('tags-list-reset', 'n_clicks'),
    ],
)
def show_tags(*_):
    if not is_user_token_valid(flask.request.cookies.get('login_token')):
        raise PreventUpdate
    tags = akb.get_tags()
    children = [
        html.Div([
            dcc.Input(
                id=dict(type='tag-priority-input', index=tag['name']),
                value=tag['priority'],
                type='number',
                step=1,
                size=3,
                placeholder='Priority',
                style={'display': 'inline-block'},
            ),
            ' ',
            html.Div(tag['name'], style={'display': 'inline-block'}),
        ])
        for tag in tags
    ]
    children.append(html.Div([
        dcc.Input(
            id='new-tag-priority-input',
            value=max((tag['priority'] for tag in akb.get_tags()), default=-1) + 1,
            type='number',
            step=1,
            size=3,
            placeholder='Priority',
            style={'display': 'inline-block'},
        ),
        ' ',
        dcc.Input(
            value='',
            id='new-tag-name-input',
            type='text',
            size=80,
            placeholder='Name of new tag',
            style={'display': 'inline-block'},
        ),
    ]))
    return children


def is_tag_name_correct(name):
    return bool(re.match(r'^[0-9a-zA-Z_\-]+$', name))


@app.callback(
    Output('tags-list-save-status', 'children'),
    [Input('tags-list-save-button', 'n_clicks')],
    state=[
        State(dict(type='tag-priority-input', index=ALL), 'id'),
        State(dict(type='tag-priority-input', index=ALL), 'value'),
        State('new-tag-priority-input', 'value'),
        State('new-tag-name-input', 'value'),
    ],
)
def set_save_status(n_clicks, tags, priorities, new_priority, new_name):
    if not n_clicks:
        raise PreventUpdate
    if not is_user_token_valid(flask.request.cookies.get('login_token')):
        return 'Error: unauthorised'
    if priorities == list(range(len(priorities))):
        raise PreventUpdate
    tags = [dict(name=tag_id['index'], priority=priority) for tag_id, priority in zip(tags, priorities)]
    if new_name:
        if not is_tag_name_correct(new_name):
            return 'Error: tag name should consist of letters, digits, underscores and hyphens only'
        tags.append(dict(name=new_name, priority=new_priority))
    akb.post_tags(tags)
    return 'saved'
