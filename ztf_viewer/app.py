import dash

js9_css = [
    "/static/js9/js9support.css",
    "/static/js9/js9.css",
]

js9_js = [
    "/static/js/js9prefs.js",
    "/static/js9/js9support.min.js",
    "/static/js9/js9.min.js",
    "/static/js9/js9plugins.js",
]


app = dash.Dash(
    __name__,
    external_stylesheets=js9_css,
    external_scripts=js9_js,
)
app.config.suppress_callback_exceptions = True
