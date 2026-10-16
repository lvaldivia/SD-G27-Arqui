import logging
import os
import socket
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as ErrorHTTPStarlette

from .config import Configuracion
from .metadata import metadatos_instancia
from .models import DatosProducto, Producto
from .repositories import Repositorio, crear_repositorio

logger = logging.getLogger("uvicorn.error")


def repositorio_actual(request: Request) -> Repositorio:
    return request.app.state.repositorio


def crear_app(repositorio=None, configuracion=None):
    @asynccontextmanager
    async def ciclo_vida(app):
        try:
            c = configuracion or Configuracion()
        except ValidationError as error:
            # No imprimir input_value: puede contener contraseñas.
            detalles = "; ".join(".".join(map(str, e["loc"])) + ": " + e["msg"]
                                 for e in error.errors(include_input=False, include_url=False))
            raise RuntimeError("Configuración inválida del .env: " + detalles) from None
        app.state.configuracion = c
        app.state.repositorio = repositorio if repositorio is not None else crear_repositorio(c)
        try:
            await run_in_threadpool(app.state.repositorio.iniciar)
        except Exception:
            raise RuntimeError("No se pudo iniciar la base de datos. Revise el .env, la red, los permisos y la tabla elegida.") from None
        app.state.metadatos = await run_in_threadpool(metadatos_instancia)
        yield

    app = FastAPI(title="Inventario · Curso AWS", description="Gestión de productos con tres motores de datos.",
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None, lifespan=ciclo_vida)
    # Orígenes permitidos para un frontend servido desde otro dominio, separados por comas.
    origenes = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origenes, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(RequestValidationError)
    async def validacion(request, error):
        return JSONResponse(status_code=422, content={"detalle": "Datos inválidos. Revise los campos.",
            "errores": [{"campo": ".".join(map(str, e["loc"])), "tipo": e["type"]}
                        for e in error.errors()]})

    @app.exception_handler(ErrorHTTPStarlette)
    async def error_http(request, error):
        detalle = {"Not Found": "Ruta no encontrada", "Method Not Allowed": "Método no permitido"}.get(str(error.detail), error.detail)
        return JSONResponse(status_code=error.status_code, content={"detalle": detalle})

    @app.exception_handler(Exception)
    async def error_general(request, error):
        logger.error("Fallo al atender la API: %s", type(error).__name__)
        return JSONResponse(status_code=503, content={"detalle": "No se pudo acceder a la base de datos. Intente nuevamente."})

    @app.get("/api/health", response_class=PlainTextResponse, summary="Comprobar el proceso sin consultar datos")
    def health():
        return "OK"

    @app.get("/api/info", summary="Consultar motor y servidor")
    def info(request: Request, repo=Depends(repositorio_actual)):
        c = request.app.state.configuracion
        try:
            responde = repo.disponible()
        except Exception:
            responde = False
        return {"motor": c.db_engine, "host_base_datos": c.dynamo_endpoint or c.dynamo_table if c.db_engine == "dynamodb" else c.db_host,
                "host_lectura": c.db_read_host or None if c.db_engine == "aurora" else None,
                "servidor": socket.gethostname(), **request.app.state.metadatos, "base_datos_disponible": responde}

    @app.get("/api/productos", response_model=list[Producto], summary="Listar productos")
    def listar(repo=Depends(repositorio_actual)):
        return repo.listar()

    @app.get("/api/productos/{identificador}", response_model=Producto, summary="Consultar un producto")
    def obtener(identificador: str, repo=Depends(repositorio_actual)):
        producto = repo.obtener(identificador)
        if producto is None:
            raise HTTPException(404, "Producto no encontrado")
        return producto

    @app.post("/api/productos", response_model=Producto, status_code=201, summary="Crear un producto")
    def crear(datos: DatosProducto, repo=Depends(repositorio_actual)):
        return repo.crear(datos)

    @app.put("/api/productos/{identificador}", response_model=Producto, summary="Actualizar un producto")
    def actualizar(identificador: str, datos: DatosProducto, repo=Depends(repositorio_actual)):
        producto = repo.actualizar(identificador, datos)
        if producto is None:
            raise HTTPException(404, "Producto no encontrado")
        return producto

    @app.delete("/api/productos/{identificador}", status_code=204, summary="Eliminar un producto")
    def eliminar(identificador: str, repo=Depends(repositorio_actual)):
        if not repo.eliminar(identificador):
            raise HTTPException(404, "Producto no encontrado")
        return Response(status_code=204)

    return app


app = crear_app()
