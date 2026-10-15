from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
import ssl
from uuid import uuid4

import boto3
import pymysql
from botocore.config import Config
from botocore.exceptions import ClientError

from .models import DatosProducto, Producto


class Repositorio(ABC):
    @abstractmethod
    def iniciar(self): ...

    @abstractmethod
    def disponible(self) -> bool: ...

    @abstractmethod
    def listar(self) -> list[Producto]: ...

    @abstractmethod
    def obtener(self, identificador: str) -> Producto | None: ...

    @abstractmethod
    def crear(self, datos: DatosProducto) -> Producto: ...

    @abstractmethod
    def actualizar(self, identificador: str, datos: DatosProducto) -> Producto | None: ...

    @abstractmethod
    def eliminar(self, identificador: str) -> bool: ...


def nuevo(datos):
    return Producto(**datos.model_dump(), id=str(uuid4()), creado_en=datetime.now(timezone.utc))


class RepositorioMySQL(Repositorio):
    def __init__(self, configuracion):
        self.c = configuracion

    def conectar(self, lectura=False, sin_base=False):
        host = self.c.db_read_host if lectura and self.c.db_engine == "aurora" and self.c.db_read_host else self.c.db_host
        # Los endpoints oficiales de RDS/Aurora usan TLS y validación de identidad.
        contexto_tls = None
        if host.lower().endswith((".rds.amazonaws.com", ".rds.amazonaws.com.cn")):
            contexto_tls = ssl.create_default_context(cafile=str(Path(__file__).with_name("rds-global-bundle.pem")))
        return pymysql.connect(
            host=host, port=self.c.db_port, user=self.c.db_user,
            password=self.c.db_password.get_secret_value(),
            database=None if sin_base else self.c.db_name, charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor, autocommit=True,
            connect_timeout=3, read_timeout=5, write_timeout=5, ssl=contexto_tls)

    def iniciar(self):
        # El nombre de la base ya fue validado; los valores usan parámetros SQL.
        with self.conectar(sin_base=True) as conexion:
            with conexion.cursor() as cursor:
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{self.c.db_name}` CHARACTER SET utf8mb4")
        with self.conectar() as conexion:
            with conexion.cursor() as cursor:
                cursor.execute("""CREATE TABLE IF NOT EXISTS productos (
                    id VARCHAR(36) PRIMARY KEY, nombre VARCHAR(120) NOT NULL,
                    precio DECIMAL(12,2) NOT NULL, stock INT NOT NULL,
                    creado_en DATETIME(6) NOT NULL)""")

    @staticmethod
    def convertir(fila):
        if fila is None:
            return None
        fila["creado_en"] = fila["creado_en"].replace(tzinfo=timezone.utc)
        return Producto(**fila)

    def disponible(self):
        # Verificar escritor y lector si están configurados.
        for lectura in (False, True):
            with self.conectar(lectura=lectura) as conexion:
                with conexion.cursor() as cursor:
                    cursor.execute("SELECT 1")
        return True

    def listar(self):
        with self.conectar(lectura=True) as conexion:
            with conexion.cursor() as cursor:
                cursor.execute("SELECT * FROM productos ORDER BY creado_en DESC, id")
                return [self.convertir(fila) for fila in cursor.fetchall()]

    def _obtener(self, identificador, lectura=True):
        with self.conectar(lectura=lectura) as conexion:
            with conexion.cursor() as cursor:
                cursor.execute("SELECT * FROM productos WHERE id=%s", (identificador,))
                return self.convertir(cursor.fetchone())

    def obtener(self, identificador):
        return self._obtener(identificador)

    def crear(self, datos):
        producto = nuevo(datos)
        with self.conectar() as conexion:
            with conexion.cursor() as cursor:
                cursor.execute("INSERT INTO productos (id,nombre,precio,stock,creado_en) VALUES (%s,%s,%s,%s,%s)",
                               (producto.id, producto.nombre, producto.precio, producto.stock,
                                producto.creado_en.replace(tzinfo=None)))
        return producto

    def actualizar(self, identificador, datos):
        # Bloquear la fila en el escritor evita carreras con un DELETE concurrente.
        with self.conectar() as conexion:
            conexion.begin()
            with conexion.cursor() as cursor:
                cursor.execute("SELECT * FROM productos WHERE id=%s FOR UPDATE", (identificador,))
                fila = cursor.fetchone()
                if fila is None:
                    conexion.rollback()
                    return None
                cursor.execute("UPDATE productos SET nombre=%s,precio=%s,stock=%s WHERE id=%s",
                               (datos.nombre, datos.precio, datos.stock, identificador))
                conexion.commit()
                return Producto(**datos.model_dump(), id=identificador,
                                creado_en=fila["creado_en"].replace(tzinfo=timezone.utc))

    def eliminar(self, identificador):
        with self.conectar() as conexion:
            with conexion.cursor() as cursor:
                cursor.execute("DELETE FROM productos WHERE id=%s", (identificador,))
                return cursor.rowcount > 0


class RepositorioDynamoDB(Repositorio):
    def __init__(self, configuracion):
        self.c = configuracion
        self.recurso = boto3.resource("dynamodb", region_name=self.c.aws_region,
            endpoint_url=self.c.dynamo_endpoint or None,
            config=Config(connect_timeout=2, read_timeout=4, retries={"max_attempts": 1}))
        self.tabla = self.recurso.Table(self.c.dynamo_table)

    def iniciar(self):
        try:
            self.tabla.load()
        except ClientError as error:
            if error.response["Error"]["Code"] != "ResourceNotFoundException" or not self.c.dynamo_auto_create:
                raise
            self.tabla = self.recurso.create_table(TableName=self.c.dynamo_table,
                KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST")
            self.tabla.wait_until_exists()
        esquema = self.tabla.key_schema
        if esquema != [{"AttributeName": "id", "KeyType": "HASH"}] or not any(
            a["AttributeName"] == "id" and a["AttributeType"] == "S" for a in self.tabla.attribute_definitions):
            raise ValueError("La tabla DynamoDB debe tener solamente id (String) como clave de partición")

    def disponible(self):
        self.tabla.load()
        return self.tabla.table_status == "ACTIVE"

    @staticmethod
    def convertir(item):
        if item is None:
            return None
        item["stock"] = int(item["stock"])
        return Producto(**item)

    def listar(self):
        elementos = []
        argumentos = {"ConsistentRead": True}
        while True:
            respuesta = self.tabla.scan(**argumentos)
            elementos.extend(self.convertir(item) for item in respuesta["Items"])
            if "LastEvaluatedKey" not in respuesta:
                break
            argumentos["ExclusiveStartKey"] = respuesta["LastEvaluatedKey"]
        return sorted(elementos, key=lambda p: (p.creado_en, p.id), reverse=True)

    def obtener(self, identificador):
        return self.convertir(self.tabla.get_item(Key={"id": identificador}, ConsistentRead=True).get("Item"))

    def crear(self, datos):
        producto = nuevo(datos)
        item = producto.model_dump()
        item["creado_en"] = producto.creado_en.isoformat()
        self.tabla.put_item(Item=item, ConditionExpression="attribute_not_exists(id)")
        return producto

    def actualizar(self, identificador, datos):
        try:
            respuesta = self.tabla.update_item(Key={"id": identificador},
                UpdateExpression="SET nombre=:nombre, precio=:precio, stock=:stock",
                ExpressionAttributeValues={":" + k: v for k, v in datos.model_dump().items()},
                ConditionExpression="attribute_exists(id)", ReturnValues="ALL_NEW")
            return self.convertir(respuesta["Attributes"])
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            raise

    def eliminar(self, identificador):
        respuesta = self.tabla.delete_item(Key={"id": identificador}, ReturnValues="ALL_OLD")
        return bool(respuesta.get("Attributes"))


def crear_repositorio(configuracion):
    if configuracion.db_engine == "dynamodb":
        return RepositorioDynamoDB(configuracion)
    return RepositorioMySQL(configuracion)
