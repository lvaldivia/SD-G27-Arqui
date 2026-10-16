from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import Configuracion
from app.main import crear_app
from app.repositories import Repositorio, nuevo


class RepositorioMemoria(Repositorio):
    def __init__(self):
        self.productos = {}

    def iniciar(self):
        pass

    def disponible(self):
        return True

    def listar(self):
        return list(self.productos.values())

    def obtener(self, identificador):
        return self.productos.get(identificador)

    def crear(self, datos):
        producto = nuevo(datos)
        self.productos[producto.id] = producto
        return producto

    def actualizar(self, identificador, datos):
        anterior = self.obtener(identificador)
        if anterior is None:
            return None
        producto = anterior.model_copy(update=datos.model_dump())
        self.productos[identificador] = producto
        return producto

    def eliminar(self, identificador):
        return self.productos.pop(identificador, None) is not None


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr("app.main.metadatos_instancia", lambda: {"instance_id": None, "zona_disponibilidad": None})
    c = Configuracion(_env_file=None, db_engine="mysql", db_host="ejemplo.local",
                      db_name="prueba", db_user="usuario", db_password="no-es-un-secreto-real")
    with TestClient(crear_app(RepositorioMemoria(), c)) as cliente:
        yield cliente


def test_crud_completo(cliente):
    assert cliente.get("/api/productos").json() == []
    respuesta = cliente.post("/api/productos", json={"nombre": "Teclado", "precio": "23.45", "stock": 3})
    assert respuesta.status_code == 201
    producto = respuesta.json()
    identificador = producto["id"]
    assert producto["creado_en"]
    assert Decimal(producto["precio"]) == Decimal("23.45")
    assert cliente.get(f"/api/productos/{identificador}").json() == producto
    assert len(cliente.get("/api/productos").json()) == 1
    for _ in range(2):
        respuesta = cliente.put(f"/api/productos/{identificador}", json={"nombre": "Ratón", "precio": 0, "stock": 0})
        assert respuesta.status_code == 200
        assert respuesta.json()["creado_en"] == producto["creado_en"]
    assert cliente.delete(f"/api/productos/{identificador}").status_code == 204
    assert cliente.get(f"/api/productos/{identificador}").status_code == 404
    assert cliente.put(f"/api/productos/{identificador}", json={"nombre": "X", "precio": 1, "stock": 1}).status_code == 404
    assert cliente.delete(f"/api/productos/{identificador}").status_code == 404


@pytest.mark.parametrize("cambios", [
    {"nombre": ""}, {"nombre": " "}, {"nombre": "x" * 121}, {"precio": -1},
    {"precio": "1.001"}, {"precio": "NaN"}, {"stock": -1}, {"stock": 1.5},
    {"stock": True}, {"stock": "1"}, {"stock": 2147483648}])
def test_validacion(cliente, cambios):
    respuesta = cliente.post("/api/productos", json={"nombre": "Producto", "precio": 1, "stock": 1, **cambios})
    assert respuesta.status_code == 422
    assert "detalle" in respuesta.json()


def test_health_no_consulta_datos(cliente):
    def fallar():
        raise RuntimeError("Base de datos caída")
    cliente.app.state.repositorio.disponible = fallar
    assert cliente.get("/health").status_code == 404
    assert cliente.get("/api/health").text == "OK"
    info = cliente.get("/api/info").json()
    assert info["base_datos_disponible"] is False
    assert info["motor"] == "mysql"
    assert info["instance_id"] is None
    assert "password" not in str(info)
    assert "no-es-un-secreto-real" not in str(info)


def test_documentacion(cliente):
    assert cliente.get("/api/docs").status_code == 200
    assert "/api/productos" in cliente.get("/api/openapi.json").json()["paths"]


def test_error_no_expone_secretos(cliente):
    def fallar():
        raise RuntimeError("contraseña privada")
    cliente.app.state.repositorio.listar = fallar
    with TestClient(cliente.app, raise_server_exceptions=False) as seguro:
        seguro.app.state.repositorio.listar = fallar
        respuesta = seguro.get("/api/productos")
        assert respuesta.status_code == 503
        assert "privada" not in respuesta.text
