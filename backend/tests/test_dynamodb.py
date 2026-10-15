import boto3
import pytest
from moto import mock_aws

from app.config import Configuracion
from app.models import DatosProducto
from app.repositories import RepositorioDynamoDB


@pytest.fixture
def repositorio(monkeypatch):
    # Credenciales ficticias, únicamente dentro de moto; nunca se accede a AWS.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "prueba")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "prueba")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    with mock_aws():
        recurso = boto3.resource("dynamodb", region_name="us-east-1")
        recurso.create_table(TableName="productos", KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST")
        c = Configuracion(_env_file=None, db_engine="dynamodb", aws_region="us-east-1", dynamo_table="productos")
        repo = RepositorioDynamoDB(c)
        repo.iniciar()
        yield repo


def test_crud_dynamodb(repositorio):
    datos = DatosProducto(nombre="Producto", precio="12.34", stock=2)
    assert repositorio.disponible()
    assert repositorio.listar() == []
    producto = repositorio.crear(datos)
    assert repositorio.obtener(producto.id) == producto
    assert repositorio.listar() == [producto]
    cambios = DatosProducto(nombre="Nuevo nombre", precio="0.10", stock=0)
    actualizado = repositorio.actualizar(producto.id, cambios)
    assert actualizado.precio == cambios.precio
    assert actualizado.creado_en == producto.creado_en
    assert repositorio.actualizar("inexistente", cambios) is None
    assert repositorio.eliminar(producto.id)
    assert not repositorio.eliminar(producto.id)
    assert repositorio.obtener(producto.id) is None


def test_scan_paginado(repositorio, monkeypatch):
    original = repositorio.tabla.scan
    monkeypatch.setattr(repositorio.tabla, "scan", lambda **kwargs: original(Limit=1, **kwargs))
    for n in range(3):
        repositorio.crear(DatosProducto(nombre=f"Producto {n}", precio="0.01", stock=n))
    assert len(repositorio.listar()) == 3
