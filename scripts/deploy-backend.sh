#!/usr/bin/env bash
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGEN="curso-productos:local"
CONTENEDOR="curso-productos"
SOLO_REINICIAR=false
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--solo-reiniciar" ) ]]; then
  echo "Uso: bash scripts/deploy-backend.sh [--solo-reiniciar]" >&2
  exit 1
fi
if [[ $# -eq 1 ]]; then SOLO_REINICIAR=true; fi
if [[ ! -f "$RAIZ/.env" ]]; then
  echo "Falta $RAIZ/.env. Ejecute: cp .env.example .env y edite las credenciales antes de continuar." >&2
  exit 1
fi
ADMIN=()
if [[ "$EUID" -ne 0 ]]; then ADMIN=(sudo); fi
if ! command -v docker >/dev/null 2>&1; then
  echo "Instalando Docker en Amazon Linux 2023..."
  "${ADMIN[@]}" dnf install -y docker
fi
"${ADMIN[@]}" systemctl enable --now docker
if [[ "$SOLO_REINICIAR" == false ]]; then
  echo "Construyendo la imagen del backend..."
  "${ADMIN[@]}" docker build -t "$IMAGEN" "$RAIZ/backend"
elif ! "${ADMIN[@]}" docker image inspect "$IMAGEN" >/dev/null 2>&1; then
  echo "La imagen no existe. Ejecute primero el script sin --solo-reiniciar." >&2
  exit 1
fi
echo "Reemplazando el contenedor con las variables actuales del .env..."
if "${ADMIN[@]}" docker container inspect "$CONTENEDOR" >/dev/null 2>&1; then
  "${ADMIN[@]}" docker rm -f "$CONTENEDOR" >/dev/null
fi
# FastAPI inicializa el repositorio antes de aceptar solicitudes.
# RDS/Aurora: RepositorioMySQL.iniciar() crea la base DB_NAME y la tabla productos.
# DynamoDB: comprueba la tabla creada manualmente en la consola de AWS.
echo "Inicializando la capa de datos según DB_ENGINE en el .env..."
echo "RDS/Aurora: se crearán la base DB_NAME y la tabla productos si no existen."
echo "DynamoDB: se comprobará la tabla que debe crear previamente en la consola de AWS."
"${ADMIN[@]}" docker run -d --name "$CONTENEDOR" --restart unless-stopped \
  --env-file "$RAIZ/.env" -p 8000:8000 \
  --log-opt max-size=10m --log-opt max-file=3 "$IMAGEN" >/dev/null
echo "Esperando la respuesta de /api/health..."
for (( intento=1; intento<=60; intento++ )); do
  if "${ADMIN[@]}" docker exec "$CONTENEDOR" python -c \
    "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).read() == b'OK'" \
    >/dev/null 2>&1; then
    echo "Inicialización de datos completada. Backend listo: /api/health responde OK en el puerto 8000."
    exit 0
  fi
  sleep 2
done
echo "El backend no inició. Revise: sudo docker logs $CONTENEDOR" >&2
exit 1
