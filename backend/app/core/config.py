import os
from typing import List, Union
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Decentralized Multi-Agent Coordination Platform"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = True

    # Postgres Settings
    POSTGRES_USER: str = "logistics_user"
    POSTGRES_PASSWORD: str = "logistics_password"
    POSTGRES_DB: str = "logistics_db"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    # Redis Settings
    REDIS_URL: str = "redis://localhost:6379/0"

    # MQTT Settings
    MQTT_BROKER_HOST: str = "localhost"
    MQTT_BROKER_PORT: int = 1883
    MQTT_USERNAME: str = ""
    MQTT_PASSWORD: str = ""
    MQTT_TLS_CA_CERT: str = ""
    MQTT_TLS_CERTFILE: str = ""
    MQTT_TLS_KEYFILE: str = ""
    AGENTIC_MAX_REPLANS: int = 2
    API_ADMIN_TOKEN: str = ""
    API_OPERATOR_TOKEN: str = ""
    DYNAMIC_AGENT_PROCESS_LIMIT: int = 200

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5173"]

    model_config = SettingsConfigDict(
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    @property
    def postgres_uri(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"


settings = Settings()
