"""Конфигурация приложения из переменных окружения."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "changeme"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.anthropic.com/v1/"
    llm_model: str = "claude-haiku-4-5"
    llm_guided_json: bool = False
    llm_timeout: int = 120
    llm_max_concurrency: int = 8
    embedding_model: str = "BAAI/bge-m3"
    embed_device: str = "cpu"
    embed_batch: int = 32
    backend_cors_origins: str = "http://localhost:5173"
    data_dir: str = "/data"
    s3_endpoint_url: str = ""
    s3_region: str = "ru-central1"
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]

    @property
    def s3_configured(self) -> bool:
        return bool(self.s3_bucket and self.s3_access_key_id and self.s3_secret_access_key)


settings = Settings()
