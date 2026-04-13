import logging

from flask import Flask

from config import Config
from modules.audit import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    init_db()

    from modules.routes import register_routes
    register_routes(app)

    return app


if __name__ == "__main__":
    app = create_app()
    logger.info("")
    logger.info("%s", "=" * 50)
    logger.info("  MediRaksha - AI Medical Report Summarizer")
    logger.info("%s", "=" * 50)
    logger.info("  Server running at: http://localhost:5000")
    logger.info("  Press Ctrl+C to stop")
    logger.info("%s", "=" * 50)
    logger.info("")
    app.run(debug=app.config["DEBUG"], host="0.0.0.0", port=5000)
