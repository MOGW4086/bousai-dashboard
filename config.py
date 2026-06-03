"""アプリケーション設定モジュール。"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent


class Config:
    """アプリケーション共通設定。環境変数から読み込む。"""

    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret")
    PORT = int(os.getenv("FLASK_PORT", 5001))
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "disaster.db"))
    LOG_DIR = Path(os.getenv("LOG_DIR", str(BASE_DIR / "logs")))
    # Phase2
    SORAMAME_API_KEY = os.getenv("SORAMAME_API_KEY", "")
    KAFUN_API_KEY = os.getenv("KAFUN_API_KEY", "")
