# Inventario de productos · Curso de Arquitectura de Soluciones en AWS

CRUD de productos con FastAPI (backend) y Angular (frontend). El motor de datos (RDS MySQL, Aurora MySQL o DynamoDB) se elige en el `.env` del backend, sin recompilar el frontend.

```text
Navegador ──HTTPS──► CloudFront ──(*)──────► S3 privado (Angular)
                         └──(/api/*)──► ALB ──:8000──► Auto Scaling Group (EC2 + Docker + FastAPI)
                                                              └──► RDS / Aurora / DynamoDB
```

## Backend

### Configuración

El backend lee un único `.env` en la raíz del repositorio. `.env.example` es la plantilla; el `.env` real tiene secretos y no se sube a Git.

```bash
cp .env.example .env
chmod 600 .env
nano .env
```

Valores sin comillas ni espacios alrededor de `=`. Variables principales:

| Variable | Uso |
| --- | --- |
| `DB_ENGINE` | `mysql`, `aurora` o `dynamodb` |
| `DB_HOST`, `DB_READ_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | RDS / Aurora (`DB_READ_HOST` opcional, solo Aurora) |
| `AWS_REGION`, `DYNAMO_TABLE` | DynamoDB (credenciales por el rol IAM de la instancia, nunca access keys) |
| `CORS_ORIGINS` | Orígenes permitidos separados por comas; `*` por defecto. Con CloudFront no hace falta CORS |

En MySQL/Aurora el backend crea la base y la tabla al arrancar. En DynamoDB la tabla `productos` (clave `id` String) se crea manualmente.

### Compilar y desplegar en EC2

En una EC2 Amazon Linux 2023 (2 GiB de RAM o más):

```bash
sudo dnf install -y git
git clone https://github.com/TU_ORGANIZACION/TU_REPOSITORIO.git
cd TU_REPOSITORIO
cp .env.example .env && chmod 600 .env && nano .env
bash scripts/deploy-backend.sh
```

El script instala Docker, construye la imagen `curso-productos:local` y levanta el contenedor `curso-productos` en el puerto 8000 con `--restart unless-stopped`. Comprobar:

```bash
curl -f http://localhost:8000/health
curl -f http://localhost:8000/api/info     # base_datos_disponible: true
```

Después de editar `.env`, recrear el contenedor sin reconstruir: `bash scripts/deploy-backend.sh --solo-reiniciar`. Para actualizar código: `git pull` y el script completo.

## Frontend

### URL de la API

La URL base está en la constante `API_BASE` de `frontend/src/app/app.ts`:

```ts
const API_BASE = '';   // vacía = mismo origen
```

- **Vacía** cuando S3 y el ALB están en la misma distribución CloudFront (producción) o con `ng serve` (usa `proxy.conf.json`).
- **URL absoluta sin barra final** (`http://localhost:8000`, `http://mi-alb-123.us-east-1.elb.amazonaws.com`) cuando el frontend se sirve desde otro origen, por ejemplo el contenedor local. El backend debe permitir ese origen en `CORS_ORIGINS`.

Cambiar la constante requiere volver a compilar.

### Compilar para S3

Desde `frontend`, borrar antes la carpeta `dist` anterior.

Con Docker (sin Node):

```bash
docker build --target export --output type=local,dest=./dist .
```

Salida en `frontend/dist`.

Con Node 22.22.3+, 24.15.0+ o 26+:

```bash
npm ci
npm run build
```

Salida en `frontend/dist/frontend/browser`.

Subir **el contenido** de la carpeta de salida a la raíz del bucket (`index.html` en la raíz) y crear una invalidación `/*` en CloudFront. Los `.js` deben quedar con `Content-Type` JavaScript y los `.css` con `text/css`.

### Ejecutar con Docker

```bash
docker build --target preview -t curso-frontend .
docker run -d --name curso-frontend -p 8080:80 curso-frontend
```

Abrir `http://localhost:8080`. Este nginx no reenvía `/api`, así que `API_BASE` debe tener una URL absoluta.

### Desarrollo local

Con el backend en `localhost:8000`: desde `frontend`, `npm ci` y `npm start`, y abrir `http://localhost:4200`.

## Despliegue en AWS

### 1. Red y seguridad

- VPC con dos subredes públicas y dos privadas en zonas distintas. RDS/Aurora en las privadas.
- Grupos de seguridad:

| Grupo | Entrada |
| --- | --- |
| `sg-alb` | 80/443 desde la lista de prefijos `com.amazonaws.global.cloudfront.origin-facing` |
| `sg-backend` | 8000 solo desde `sg-alb` |
| `sg-datos` | 3306 solo desde `sg-backend` |

- Rol IAM para EC2 con `AmazonSSMManagedInstanceCore` y, para DynamoDB, permisos `GetItem`, `PutItem`, `UpdateItem`, `DeleteItem`, `Scan` y `DescribeTable` sobre la tabla.

### 2. EC2 base

Crear la EC2 con `sg-backend`, el rol IAM y en metadatos **IMDSv2 obligatorio con hop limit = 2** (sin esto el contenedor no obtiene credenciales ni `instance_id`). Desplegar el backend como en [Compilar y desplegar en EC2](#compilar-y-desplegar-en-ec2) y verificar `/api/info`.

### 3. AMI

Desde la EC2 verificada: **Actions → Image and templates → Create image**. Docker arranca con el sistema y el contenedor tiene `--restart unless-stopped`, así que cada instancia creada desde la AMI levanta la API sola.

La AMI incluye el `.env` con sus secretos. Si cambia el `.env` (por ejemplo al pasar a Aurora o DynamoDB) hay que crear una AMI nueva.

### 4. Launch template

- AMI creada en el paso anterior.
- Grupo de seguridad `sg-backend` y el rol IAM.
- Metadatos: IMDSv2 obligatorio, hop limit = 2.
- Sin subred (la define el Auto Scaling Group).

### 5. Target group y ALB

- Target group tipo **Instances**, HTTP, puerto **8000**, health check en **`/health`** con código 200.
- ALB público en las dos subredes públicas con `sg-alb`. Listener con acción predeterminada 403 y una regla que reenvía al target group solo si la cabecera `X-Origen-Curso` coincide con un valor secreto que añade CloudFront.

### 6. Auto Scaling Group

- Usa el launch template, las subredes de dos zonas y se adjunta al target group.
- Health check tipo **ELB**.
- Para publicar una AMI nueva: nueva versión del launch template e **instance refresh** del grupo.

### 7. S3 y CloudFront

- Bucket privado (bloqueo de acceso público, sin website hosting), origen con OAC.
- Distribución:

| Ajuste | Valor |
| --- | --- |
| Default root object | `index.html` |
| Comportamiento `*` | Origen S3; GET y HEAD; redirigir HTTP a HTTPS |
| Comportamiento `/api/*` | Origen ALB con cabecera `X-Origen-Curso`; todos los métodos; **CachingDisabled**; **AllViewerExceptHostHeader** |

Como frontend y API comparten el dominio de CloudFront, no hay CORS y `API_BASE` queda vacía.

### 8. Frontend

Compilar y subir como en [Compilar para S3](#compilar-para-s3), e invalidar `/*`.

## Limpieza

Eliminar Auto Scaling Group, launch template, AMI y sus snapshots, EC2, ALB y target group, CloudFront, bucket, RDS/Aurora, tabla DynamoDB, roles y NAT o IP públicas creadas para el ejercicio.
