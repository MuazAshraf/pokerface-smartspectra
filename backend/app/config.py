from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# One .env at the repo root is shared by Electron and the backend.
ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    openai_api_key: SecretStr
    openai_model: str = "gpt-5.4-mini"
    llm_timeout_s: float = 8.0
    # Electron pages loaded with loadFile() connect with Origin "file://".
    allowed_origins: list[str] = ["file://"]


settings = Settings()
