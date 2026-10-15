from app.config import Configuracion
from app.repositories import RepositorioMySQL


def test_aurora_separa_lector_y_escritor(monkeypatch):
    conexiones = []
    monkeypatch.setattr("app.repositories.pymysql.connect", lambda **kwargs: conexiones.append(kwargs) or object())
    c = Configuracion(_env_file=None, db_engine="aurora", db_host="escritor", db_read_host="lector",
                      db_name="curso", db_user="usuario", db_password="prueba")
    repo = RepositorioMySQL(c)
    repo.conectar(lectura=True)
    repo.conectar()
    assert [conexion["host"] for conexion in conexiones] == ["lector", "escritor"]
    assert all(conexion["connect_timeout"] == 3 for conexion in conexiones)


def test_mysql_ignora_endpoint_lector(monkeypatch):
    conexiones = []
    monkeypatch.setattr("app.repositories.pymysql.connect", lambda **kwargs: conexiones.append(kwargs) or object())
    c = Configuracion(_env_file=None, db_engine="mysql", db_host="escritor", db_read_host="ignorado",
                      db_name="curso", db_user="usuario", db_password="prueba")
    RepositorioMySQL(c).conectar(lectura=True)
    assert conexiones[0]["host"] == "escritor"


def test_endpoint_aws_activa_tls_con_verificacion(monkeypatch):
    conexiones = []
    monkeypatch.setattr("app.repositories.pymysql.connect", lambda **kwargs: conexiones.append(kwargs) or object())
    c = Configuracion(_env_file=None, db_engine="aurora", db_host="curso.cluster-ejemplo.us-east-1.rds.amazonaws.com",
                      db_name="curso", db_user="usuario", db_password="prueba")
    RepositorioMySQL(c).conectar()
    assert conexiones[0]["ssl"].check_hostname is True
