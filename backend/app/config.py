from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Configuracion(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)
    db_engine: Literal["mysql", "aurora", "dynamodb"]
    db_host: str = ""
    db_read_host: str = ""
    db_port: int = Field(default=3306, ge=1, le=65535)
    db_name: str = ""
    db_user: str = ""
    db_password: SecretStr = SecretStr("")
    aws_region: str = ""
    dynamo_table: str = ""
    dynamo_auto_create: bool = False
    dynamo_endpoint: str = ""

    @model_validator(mode="after")
    def validar_motor(self):
        campos = ("aws_region", "dynamo_table") if self.db_engine == "dynamodb" else (
            "db_host", "db_name", "db_user", "db_password")
        faltantes = [c.upper() for c in campos if not (
            getattr(self, c).get_secret_value() if c == "db_password" else getattr(self, c))]
        if faltantes:
            raise ValueError("Faltan variables para el motor elegido: " + ", ".join(faltantes))
        if self.db_engine != "dynamodb":
            import re
            if not re.fullmatch(r"[a-zA-Z0-9_]{1,64}", self.db_name):
                raise ValueError("DB_NAME debe tener de 1 a 64 letras, números o guiones bajos")
        if self.dynamo_auto_create and not self.dynamo_endpoint:
            raise ValueError("DYNAMO_AUTO_CREATE=true requiere DYNAMO_ENDPOINT de pruebas locales")
        return self
