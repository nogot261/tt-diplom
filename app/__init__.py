from __future__ import annotations

import os
from pathlib import Path

from flask import Flask

from .db import init_app as init_db_app, init_db
from .routes import bp


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY", "dev-change-me"),
        DATABASE_PATH=os.getenv("DATABASE_PATH", str(Path(app.instance_path) / "portal.db")),
        TESTING=False,
    )

    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db_path = Path(app.config["DATABASE_PATH"])
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    app.config["DATABASE_PATH"] = str(db_path)

    init_db_app(app)
    app.register_blueprint(bp)

    with app.app_context():
        init_db(seed=True)

    return app
