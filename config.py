import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "mediraksha-dev-secret-change-in-production")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///data/mediraksha.db")
    MAX_AUDIT = int(os.getenv("MAX_AUDIT", "100"))
    MAX_REPORT_LENGTH = int(os.getenv("MAX_REPORT_LENGTH", "5000"))
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
