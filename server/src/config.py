from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mongodb_url: str = Field(default="mongodb://localhost:27017/ios_ranking")
    jwt_secret: str = Field(default="change-me")
    jwt_algorithm: str = Field(default="HS256")
    jwt_expire_hours: int = Field(default=24)
    aes_key: str = Field(default="change-me-to-a-32-byte-hex-key-00")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    debug: bool = Field(default=False)
    ssl_enabled: bool = Field(default=False)
    ssl_certfile: Optional[str] = Field(default=None)
    ssl_keyfile: Optional[str] = Field(default=None)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
