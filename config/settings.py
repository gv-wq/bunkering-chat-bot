import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent


def load_environment():
    env = os.getenv("APP_ENV", "development")

    env_file = BASE_DIR / f".env.{env}"
    if not env_file.exists():
        raise RuntimeError(f"Environment file not found: {env_file}")

    load_dotenv(env_file)
    return env


ENV = load_environment()


def require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable missing: {name}")
    return value
