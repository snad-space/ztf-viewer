import re
from dash import html, dcc, Input, Output, State, ALL
from dash.exceptions import PreventUpdate

from ztf_viewer.akb import akb
from ztf_viewer.app import app


def get_layout(pathname):
    return html.Div([
        html.H2('Anomaly knowledge database tags', id='header-tags'),
        html.H3('Instruction for attaching the labels (tags)'),
        html.H4('Artefacts'),
        html.P(
            '''In case of any kind of artefacts, tag «artefact». 
            If type of artefact is known (e.g., «spike»), tag it as well.
            If in doubt that it is an artefact, also tag «uncertain».'''
        ),
        html.H4('Variable stars and supernovae'),
        html.P(
            '''In case subtype (e.g., «CEP», «CCSN») is known, tag only it.
            If subtype is not given (or not presented in tags), just tag the common type (e.g., «Eclipsing»).
            If type/subtype is uncertain, the tag «uncertain» also has to be added.'''
        ),
        html.P(
            '''If an object is not presented in any known catalogs and databases, tag «non-catalogued».
            If an object is known to be variable without precise type, tag «VAR».'''
        ),
        html.P(
            '''Any additional comments and classification put in «Description».
            '''
        ),
        html.H4('Examples'),
        html.Ul(
            [
                html.Li('You found a variable object that is not listed in any catalogs. The tags will be «VAR», «non-catalogued».'),
                html.Li('You found a Type Ia supernova candidate that is not listed in any catalogs. The tags will be «SN Ia», «non-catalogued», «uncertain».'),
                html.Li('You found a plane track on the image. The tags will be «artefact», «track».'),
                html.Li('You found a known transient of unknown nature. The tags will be «transient».'),
            ],
        ),
        html.H3('Tags'),
        html.Div(
            [
                html.Div('Login to edit tags', id='tags-list'),
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
    if not akb.is_token_valid():
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
            html.B(tag['name'], style={'display': 'inline-block'}),
            ' ',
            html.Div(tag['description'], style={'display': 'inline-block'}),
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
            size=20,
            placeholder='Name of new tag',
            style={'display': 'inline-block'},
        ),
        ' ',
        dcc.Input(
            value='',
            id='new-tag-description-input',
            type='text',
            size=80,
            placeholder='Description of new tag',
            style={'display': 'inline-block'},
        ),
    ]))
    return children


def is_tag_name_correct(name):
    return bool(re.match(r'^[0-9a-zA-Z_\-]+$', name))


def are_tags_priorities_unique(priorities):
    return len(priorities) == len(set(priorities))


@app.callback(
    Output('tags-list-save-status', 'children'),
    [Input('tags-list-save-button', 'n_clicks')],
    [
        State(dict(type='tag-priority-input', index=ALL), 'id'),
        State(dict(type='tag-priority-input', index=ALL), 'value'),
        State('new-tag-priority-input', 'value'),
        State('new-tag-name-input', 'value'),
        State('new-tag-description-input', 'value'),
    ],
)
def set_save_status(n_clicks, tags, priorities, new_priority, new_name, new_description):
    if not n_clicks:
        raise PreventUpdate
    if not akb.is_token_valid():
        return 'Error: unauthorised'
    tags = [dict(name=tag_id['index'], priority=priority) for tag_id, priority in zip(tags, priorities)]
    if new_name:
        if not is_tag_name_correct(new_name):
            return 'Error: tag name should consist of letters, digits, underscores and hyphens only'
        tags.append(dict(name=new_name, priority=new_priority, description=new_description))
    if not are_tags_priorities_unique([tag['priority'] for tag in tags]):
        return 'Error: tag priorities should be unique'
    akb.post_tags(tags)
    return 'saved'
