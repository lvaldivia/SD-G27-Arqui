import pytest
from pydantic import ValidationError

from app.config import Configuracion


@pytest.fixture(autouse=True)
def entorno_aislado(monkeypatch):
    for nombre in Configuracion.model_fields:
        monkeypatch.delenv(nombre.upper(), raising=False)


def test_variables_del_motor_obligatorias():
    with pytest.raises(ValidationError, match="DB_HOST"):
        Configuracion(_env_file=None, db_engine="mysql")
    with pytest.raises(ValidationError, match="AWS_REGION"):
        Configuracion(_env_file=None, db_engine="dynamodb")


def test_autocreacion_solo_local():
    with pytest.raises(ValidationError, match="DYNAMO_ENDPOINT"):
        Configuracion(_env_file=None, db_engine="dynamodb", aws_region="us-east-1",
                      dynamo_table="productos", dynamo_auto_create=True)


def test_nombre_base_seguro():
    with pytest.raises(ValidationError, match="DB_NAME"):
        Configuracion(_env_file=None, db_engine="aurora", db_host="host", db_user="usuario",
                      db_password="prueba", db_name="base`; DROP DATABASE base;")
