from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://leadagent:leadagent@localhost:5432/leadagent"
    anthropic_api_key: str | None = None
    agent_model: str = "claude-sonnet-5"
    scheduler_poll_interval_seconds: int = 30


settings = Settings()
