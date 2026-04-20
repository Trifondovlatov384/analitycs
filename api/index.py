from app import create_app

_dash_app = create_app()
app = _dash_app.server
