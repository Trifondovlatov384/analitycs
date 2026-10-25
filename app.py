"""Local entrypoint — thin wrapper around the JSON API + static shell."""

from __future__ import annotations

import os

from api.index import app


def create_app():
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8050"))
    app.run(host="127.0.0.1", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
