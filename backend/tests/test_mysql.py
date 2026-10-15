import os

import pytest

from app.config import Configuracion
from app.models import DatosProducto
from app.repositories import RepositorioMySQL


@pytest.mark.skipif(os.getenv("PRUEBA_MYSQL") != "true", reason="Requiere MySQL local y PRUEBA_MYSQL=true")
def test_mysql_real():
    c = Configuracion()
    assert c.db_engine in ("mysql", "aurora")
    repo = RepositorioMySQL(c)
    repo.iniciar()
    repo.iniciar()
    producto = repo.crear(DatosProducto(nombre="Producto de prueba", precio="23.45", stock=4))
    try:
        assert repo.disponible()
        assert repo.obtener(producto.id).precio == producto.precio
        assert any(p.id == producto.id for p in repo.listar())
        cambios = DatosProducto(nombre="Actualizado", precio="0.10", stock=0)
        assert repo.actualizar(producto.id, cambios).nombre == "Actualizado"
        assert repo.actualizar(producto.id, cambios) is not None
    finally:
        assert repo.eliminar(producto.id)
    assert repo.obtener(producto.id) is None
    assert repo.actualizar(producto.id, cambios) is None
    assert not repo.eliminar(producto.id)
