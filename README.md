# Inventario de productos · Curso de Arquitectura de Soluciones en AWS

CRUD de productos con FastAPI (backend) y Angular (frontend). El motor de datos (RDS MySQL, Aurora MySQL o DynamoDB) se elige en el `.env` del backend, sin recompilar el frontend.

```text
Navegador ──HTTPS──► CloudFront ──(*)───────► S3 privado (Angular)
                         └──(/api/*)──► ALB :80 ──► Target group :8000 ──► Auto Scaling Group
                                                                         (EC2 + Docker + FastAPI)
                                                                                  │
                                                                 RDS MySQL / Aurora / DynamoDB
```

Todo se crea en la región **us-east-1** usando la **VPC default**: no hace falta crear VPC, subredes, Internet Gateway ni NAT.

## Backend

### Configuración (`.env`)

El backend lee un único `.env` en la raíz del repositorio. `.env.example` es la plantilla; el `.env` real tiene secretos y no se sube a Git.

```bash
cp .env.example .env
chmod 600 .env
nano .env
```

Valores sin comillas ni espacios alrededor de `=`.

| Variable | Uso |
| --- | --- |
| `DB_ENGINE` | `mysql`, `aurora` o `dynamodb` |
| `DB_HOST`, `DB_READ_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | RDS / Aurora (`DB_READ_HOST` opcional, solo Aurora) |
| `AWS_REGION`, `DYNAMO_TABLE` | DynamoDB (credenciales por el rol IAM de la instancia, nunca access keys) |
| `CORS_ORIGINS` | Orígenes permitidos separados por comas; `*` por defecto. Con CloudFront no hace falta CORS |

En MySQL/Aurora el backend crea la base `DB_NAME` y la tabla al arrancar. En DynamoDB la tabla se crea manualmente (ver [paso 4](#4-tabla-dynamodb-opcional)).

### Compilar y desplegar en una EC2

```bash
sudo dnf install -y git
git clone https://github.com/lvaldivia/SD-G27-Arqui.git
cd SD-G27-Arqui
cp .env.example .env && chmod 600 .env && nano .env
bash scripts/deploy-backend.sh
```

El script instala Docker, construye la imagen `curso-productos:local` y levanta el contenedor `curso-productos` en el puerto **8000** con `--restart unless-stopped`. Comprobar:

```bash
curl -f http://localhost:8000/api/health    # OK
curl -s http://localhost:8000/api/info      # "base_datos_disponible": true
```

- Después de editar `.env`: `bash scripts/deploy-backend.sh --solo-reiniciar` (recrea el contenedor sin reconstruir).
- Para actualizar código: `git pull` y `bash scripts/deploy-backend.sh`.
- Logs: `sudo docker logs --tail 100 curso-productos`.

Todas las rutas del backend están bajo `/api`: `/api/health`, `/api/info`, `/api/productos` y Swagger en `/api/docs`.

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

### Ejecutar con Docker

```bash
docker build --target preview -t curso-frontend .
docker run -d --name curso-frontend -p 8080:80 curso-frontend
```

Abrir `http://localhost:8080`. Este nginx no reenvía `/api`, así que `API_BASE` debe tener una URL absoluta.

### Desarrollo local

Con el backend en `localhost:8000`: desde `frontend`, `npm ci` y `npm start`, y abrir `http://localhost:4200`.

## Despliegue en AWS con la VPC default

### Resumen de lo que se crea

| # | Recurso | Nombre sugerido |
| --- | --- | --- |
| 1 | Grupo de seguridad del ALB | `alb-sg` |
| 1 | Grupo de seguridad del backend (EC2) | `backend-sg` |
| 1 | Grupo de seguridad de la base de datos | `rds-sg` |
| 2 | Rol IAM de las EC2 | `backend-rol` |
| 3 | Base de datos RDS MySQL | `rds-curso-productos` |
| 4 | Tabla DynamoDB (opcional, fase 3) | `productos` |
| 5 | EC2 base | `backend-base` |
| 6 | AMI | `backend-ami-v1` |
| 7 | Launch template | `backend-lt` |
| 8 | Target group | `backend-tg` |
| 9 | Application Load Balancer | `backend-alb` |
| 10 | Auto Scaling Group | `backend-asg` |
| 11 | Bucket S3 del frontend | `NOMBRE-UNICO-frontend` |
| 12 | Distribución CloudFront | — |

La VPC default ya trae una subred pública por zona de disponibilidad, con ruta al Internet Gateway y *auto-assign public IPv4* activado. Todas las instancias salen a Internet (git, Docker Hub, DynamoDB, SSM) sin NAT. RDS queda en esas mismas subredes pero **sin acceso público**, protegido por su grupo de seguridad. En producción la base iría en subredes privadas.

### 1. Grupos de seguridad

EC2 → Security groups → Create security group, en la **VPC default**. Crearlos en este orden, porque cada uno referencia al anterior.

**`alb-sg`**: tráfico de CloudFront hacia el ALB.

| Dirección | Tipo | Puerto | Origen / destino |
| --- | --- | --- | --- |
| Entrada | HTTP | 80 | Lista de prefijos `com.amazonaws.global.cloudfront.origin-facing` |
| Salida | Todo el tráfico | Todos | `0.0.0.0/0` (por defecto) |

- No abrir 80 a `0.0.0.0/0`: solo CloudFront debe llegar al ALB.
- No agregar también 443 con la lista de prefijos: cuenta como ~55 reglas y el límite por grupo es 60.

**`backend-sg`**: tráfico del ALB hacia las EC2.

| Dirección | Tipo | Puerto | Origen / destino |
| --- | --- | --- | --- |
| Entrada | TCP personalizado | **8000** | `alb-sg` |
| Salida | Todo el tráfico | Todos | `0.0.0.0/0` (por defecto) |

No hace falta SSH: se entra por Session Manager.

**`rds-sg`**: tráfico de las EC2 hacia la base.

| Dirección | Tipo | Puerto | Origen / destino |
| --- | --- | --- | --- |
| Entrada | MySQL/Aurora | 3306 | `backend-sg` |

### 2. Rol IAM de las EC2

IAM → Roles → Create role.

1. Trusted entity: **AWS service → EC2**.
2. Adjuntar la política administrada **`AmazonSSMManagedInstanceCore`** (Session Manager).
3. Nombre: `backend-rol`.
4. En el rol creado: **Add permissions → Create inline policy → JSON**. Reemplazar `TU_CUENTA` y `NOMBRE-UNICO-frontend`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3ListarBucket",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::NOMBRE-UNICO-frontend"
    },
    {
      "Sid": "S3CopiarArchivos",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::NOMBRE-UNICO-frontend/*"
    },
    {
      "Sid": "DynamoCrudProductos",
      "Effect": "Allow",
      "Action": [
        "dynamodb:DescribeTable",
        "dynamodb:Scan",
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem"
      ],
      "Resource": "arn:aws:dynamodb:us-east-1:TU_CUENTA:table/productos"
    },
    {
      "Sid": "CloudFrontInvalidar",
      "Effect": "Allow",
      "Action": ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"],
      "Resource": "arn:aws:cloudfront::TU_CUENTA:distribution/*"
    }
  ]
}
```

- S3: permite `aws s3 cp`, `ls`, `sync` y `rm` sobre el bucket del frontend desde la instancia ([paso 13](#13-compilar-y-subir-el-frontend-desde-la-instancia)).
- DynamoDB: exactamente las operaciones que usa el backend; no permite crear ni borrar tablas.
- CloudFront: invalidar la caché después de subir el frontend. Cuando exista la distribución se puede cambiar `distribution/*` por `distribution/ID_DISTRIBUCION`.

### 3. RDS MySQL

RDS → Databases → Create database. Con la VPC default **no se crea un DB subnet group**: RDS usa el `default` que ya incluye todas sus subredes.

| Campo | Valor |
| --- | --- |
| Creation method | Standard create |
| Engine | MySQL 8.4 (u 8.0) |
| Templates | Free tier (o Dev/Test) |
| Deployment | Single-AZ |
| DB instance identifier | `rds-curso-productos` |
| Master username | `administrador` |
| Credentials management | Self managed (guardar la contraseña) |
| Instance class | `db.t4g.micro` |
| Storage | gp3, 20 GiB, sin storage autoscaling |
| Compute resource | Don't connect to an EC2 compute resource |
| VPC | Default VPC |
| DB subnet group | `default` |
| Public access | **No** |
| VPC security group | Choose existing → **`rds-sg`** (quitar `default`) |
| Port | 3306 |
| Initial database name | Vacío (el backend crea `curso_productos`) |

Esperar el estado **Available** y copiar el **Endpoint** (Connectivity & security). Va en `DB_HOST` del `.env`:

```dotenv
DB_ENGINE=mysql
DB_HOST=rds-curso-productos.xxxxxxxx.us-east-1.rds.amazonaws.com
DB_READ_HOST=
DB_PORT=3306
DB_NAME=curso_productos
DB_USER=administrador
DB_PASSWORD=TU_CONTRASENA
```

Usar el endpoint real: el backend valida el certificado TLS de RDS con ese nombre.

### 4. Tabla DynamoDB (opcional)

Solo para la fase DynamoDB. DynamoDB → Tables → Create table:

- Nombre: `productos`.
- Partition key: **`id`**, tipo **String**. Sin sort key.
- Capacidad: **On-demand**.

En el `.env`:

```dotenv
DB_ENGINE=dynamodb
AWS_REGION=us-east-1
DYNAMO_TABLE=productos
DYNAMO_AUTO_CREATE=false
DYNAMO_ENDPOINT=
```

No poner `AWS_ACCESS_KEY_ID` ni `AWS_SECRET_ACCESS_KEY`: boto3 usa las credenciales del rol `backend-rol`.

### 5. EC2 base

EC2 → Launch instance.

| Campo | Valor |
| --- | --- |
| Nombre | `backend-base` |
| AMI | Amazon Linux 2023 |
| Tipo | `t3.small` (2 GiB, necesarios para construir la imagen) |
| Key pair | Proceed without a key pair |
| Network → VPC | Default VPC |
| Network → Subnet | Cualquiera (por ejemplo `us-east-1a`) |
| Auto-assign public IP | Enable |
| Security group | Select existing → **`backend-sg`** |
| Advanced → IAM instance profile | `backend-rol` |
| Advanced → Metadata version | **V2 only (token required)** |
| Advanced → Metadata response hop limit | **2** |

El hop limit 2 permite al contenedor Docker obtener las credenciales del rol y el `instance_id`; sin él DynamoDB falla y `/api/info` muestra `null`.

Conectarse con **Connect → Session Manager** y desplegar el backend como en [Compilar y desplegar en una EC2](#compilar-y-desplegar-en-una-ec2), con el `.env` del paso 3 (o 4). Verificar `curl -s http://localhost:8000/api/info` antes de seguir.

### 6. AMI

EC2 → Instances → `backend-base` → **Actions → Image and templates → Create image**.

- Nombre: `backend-ami-v1`.
- Esperar el estado **Available** en EC2 → AMIs.

Docker arranca con el sistema y el contenedor tiene `--restart unless-stopped`: cada instancia creada desde la AMI levanta la API sola, sin user data.

La AMI incluye el `.env` con sus secretos. Si cambia el `.env` o el código, hay que crear una AMI nueva (ver [Actualizar](#actualizar-backend-o-env)).

### 7. Launch template

EC2 → Launch templates → Create launch template.

| Campo | Valor |
| --- | --- |
| Nombre | `backend-lt` |
| Auto Scaling guidance | Marcado |
| AMI | My AMIs → `backend-ami-v1` |
| Tipo | `t3.micro` o `t3.small` |
| Key pair | Don't include |
| Network settings → Subnet | **Don't include** (lo define el Auto Scaling Group) |
| Security groups | **`backend-sg`** |
| Advanced → IAM instance profile | `backend-rol` |
| Advanced → Metadata version | **V2 only** |
| Advanced → Metadata response hop limit | **2** |

### 8. Target group

EC2 → Target groups → Create target group.

| Campo | Valor |
| --- | --- |
| Target type | Instances |
| Nombre | `backend-tg` |
| Protocol / Port | HTTP / **8000** |
| VPC | Default VPC |
| Health check path | **`/api/health`** |
| Health check port | Traffic port |
| Success codes | 200 |

No registrar instancias: lo hace el Auto Scaling Group.

El puerto debe ser **8000**, el del contenedor. Un target group en el puerto 80 deja los targets *unhealthy* (`Target.Timeout`) y el ALB responde **504**.

### 9. Application Load Balancer

EC2 → Load balancers → Create → Application Load Balancer.

| Campo | Valor |
| --- | --- |
| Nombre | `backend-alb` |
| Scheme | Internet-facing, IPv4 |
| VPC | Default VPC |
| Mappings | Al menos 2 zonas (por ejemplo `us-east-1a` y `us-east-1b`) |
| Security groups | **`alb-sg`** (quitar `default`) |
| Listener | HTTP : 80 → forward a `backend-tg` |

Después de crearlo, restringir el acceso a CloudFront con una cabecera secreta. Listeners → HTTP:80 → **Manage rules**:

1. **Default action**: cambiar a *Return fixed response*, código **403**.
2. **Add rule**:
   - Condición: *HTTP header* `X-Origen-Curso` = un valor largo y aleatorio (guardarlo, no subirlo al repo).
   - Acción: forward a `backend-tg`.

Copiar el **DNS name** del ALB para CloudFront.

### 10. Auto Scaling Group

EC2 → Auto Scaling Groups → Create Auto Scaling group.

| Paso | Valor |
| --- | --- |
| Nombre | `backend-asg` |
| Launch template | `backend-lt`, versión Latest |
| VPC | Default VPC |
| Subnets | Las mismas zonas del ALB (por ejemplo `us-east-1a` y `us-east-1b`) |
| Load balancing | Attach to an existing load balancer → Choose from target groups → `backend-tg` |
| Health checks | Activar **Elastic Load Balancing health checks**, grace period 120 s |
| Capacidad | Deseada 2, mínima 2, máxima 4 |
| Scaling policy (opcional) | Target tracking, CPU promedio 60 % |

Verificar en `backend-tg` → Targets que las instancias pasan a **healthy**. Después se puede detener o terminar `backend-base`.

### 11. Bucket S3 del frontend

S3 → Create bucket.

| Campo | Valor |
| --- | --- |
| Nombre | Único global, por ejemplo `sd-g27-arqui-frontend` |
| Región | us-east-1 |
| Object Ownership | ACLs disabled |
| Block all public access | **Activado** |
| Cifrado | SSE-S3 |
| Static website hosting | No activar |

Compilar el frontend con `API_BASE = ''` ([Compilar para S3](#compilar-para-s3)) y subir **el contenido** de la carpeta de salida a la raíz del bucket: `index.html` debe quedar en la raíz, no dentro de `dist/` o `browser/`. Desde una máquina con el AWS CLI:

```bash
aws s3 sync ./dist s3://sd-g27-arqui-frontend/ --delete
```

Los `.js` deben quedar con `Content-Type` JavaScript y los `.css` con `text/css` (`aws s3 sync` lo hace automáticamente).

### 12. Distribución CloudFront

CloudFront → Create distribution.

**Origen 1: S3** (se configura al crear la distribución)

| Campo | Valor |
| --- | --- |
| Origin domain | El bucket (`NOMBRE.s3.us-east-1.amazonaws.com`, no el endpoint *website*) |
| Origin access | **Origin access control settings** → Create new OAC (Sign requests: Always) |

**Comportamiento por defecto (`*`)**

| Campo | Valor |
| --- | --- |
| Viewer protocol policy | Redirect HTTP to HTTPS |
| Allowed methods | GET, HEAD |
| Cache policy | CachingOptimized |

**Settings**

| Campo | Valor |
| --- | --- |
| Default root object | **`index.html`** |
| WAF | Do not enable |

Al crear la distribución, CloudFront muestra la **política del bucket** para el OAC: copiarla en S3 → bucket → Permissions → Bucket policy. Queda así:

```json
{
  "Version": "2008-10-17",
  "Statement": [{
    "Sid": "AllowCloudFrontServicePrincipal",
    "Effect": "Allow",
    "Principal": {"Service": "cloudfront.amazonaws.com"},
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::NOMBRE-UNICO-frontend/*",
    "Condition": {"ArnLike": {"AWS:SourceArn": "arn:aws:cloudfront::TU_CUENTA:distribution/ID_DISTRIBUCION"}}
  }]
}
```

**Origen 2: ALB** (Origins → Create origin)

| Campo | Valor |
| --- | --- |
| Origin domain | DNS name de `backend-alb` |
| Protocol | **HTTP only**, puerto 80 |
| Add custom header | `X-Origen-Curso` = el mismo valor de la regla del ALB |

**Comportamiento `/api/*`** (Behaviors → Create behavior)

| Campo | Valor |
| --- | --- |
| Path pattern | `/api/*` |
| Origin | El ALB |
| Viewer protocol policy | Redirect HTTP to HTTPS |
| Allowed methods | GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE |
| Cache policy | **CachingDisabled** |
| Origin request policy | **AllViewerExceptHostHeader** |

- No configurar *error pages* que conviertan 403/404 en `index.html`.
- Solo lo que empieza por `/api/` llega al backend; cualquier otra ruta (por ejemplo `/health`) va a S3.
- Frontend y API comparten el dominio de CloudFront: no hay CORS y `API_BASE` queda vacía.
- Después de cada subida del frontend: **Invalidations → Create → `/*`**.

### 13. Compilar y subir el frontend desde la instancia

Se puede generar el HTML y subirlo a S3 desde `backend-base`, sin instalar Node ni configurar access keys: el AWS CLI de Amazon Linux usa el rol `backend-rol` y su política del [paso 2](#2-rol-iam-de-las-ec2) (`S3ListarBucket`, `S3CopiarArchivos` y `CloudFrontInvalidar`).

Conectarse por Session Manager y, desde la raíz del repositorio:

```bash
cd ~/SD-G27-Arqui        # o la carpeta donde se clonó
git pull

# 1. Valores de este despliegue
BUCKET=sd-g27-arqui-frontend
DISTRIBUCION=E1234567890ABC      # ID de la distribución CloudFront
API=''                           # vacía con CloudFront; o 'http://DNS-DEL-ALB' sin barra final

# 2. Cambiar la constante API_BASE
sed -i "s#^const API_BASE = .*#const API_BASE = '${API}';#" frontend/src/app/app.ts
grep -n "^const API_BASE" frontend/src/app/app.ts

# 3. Compilar Angular dentro de Docker y extraer el HTML/JS/CSS
sudo docker build --target build -t curso-frontend-build frontend
rm -rf ~/frontend-dist
ID=$(sudo docker create curso-frontend-build)
sudo docker cp "$ID":/app/dist/frontend/browser ~/frontend-dist
sudo docker rm "$ID"
sudo chown -R "$USER" ~/frontend-dist
ls ~/frontend-dist               # debe verse index.html junto a los .js y .css

# 4. Subir el contenido a la raíz del bucket
aws s3 sync ~/frontend-dist/ "s3://$BUCKET/" --delete
aws s3 ls "s3://$BUCKET/"

# 5. Invalidar la caché de CloudFront
aws cloudfront create-invalidation --distribution-id "$DISTRIBUCION" --paths "/*"

# 6. Dejar app.ts como en el repositorio para que el próximo git pull no choque
git checkout -- frontend/src/app/app.ts
```

Qué hace la compilación (punto 3):

| Comando | Para qué |
| --- | --- |
| `docker build --target build -t curso-frontend-build frontend` | Ejecuta solo la etapa `build` del `frontend/Dockerfile` (Node 22, `npm ci`, `npm run build`). El resultado queda **dentro de la imagen** `curso-frontend-build`, todavía no en una carpeta visible |
| `rm -rf ~/frontend-dist` | Borra la salida de una compilación anterior. Evita mezclar `.js` viejos (cada compilación cambia sus nombres) y que `docker cp` copie dentro de la carpeta existente creando `frontend-dist/browser/` |
| `ID=$(docker create curso-frontend-build)` | De una imagen no se copian archivos directamente: crea un contenedor apagado y guarda su ID |
| `docker cp "$ID":/app/dist/frontend/browser ~/frontend-dist` | Copia el HTML/JS/CSS compilado desde el contenedor a `~/frontend-dist` en la EC2 |
| `docker rm "$ID"` | Borra el contenedor temporal; ya no hace falta |
| `chown -R "$USER" ~/frontend-dist` | Los archivos copiados con `sudo` quedan de `root`; los pasa al usuario actual para subirlos sin `sudo` |

```text
código Angular ──docker build──► imagen ──docker create + docker cp──► ~/frontend-dist ──aws s3 sync──► bucket S3
```

- Se usa `--target build` + `docker cp` en lugar de `--output`, porque el Docker de Amazon Linux no trae BuildKit/buildx.
- La compilación necesita unos 2 GiB de RAM: hacerla en `backend-base` (`t3.small`), no en una instancia `t3.micro` del Auto Scaling Group.
- `aws s3 sync` asigna el `Content-Type` correcto a `.js`, `.css` y `.html`. `--delete` borra del bucket los archivos de compilaciones anteriores.
- Si `aws` responde *AccessDenied*: revisar que la instancia tenga `backend-rol` y que el nombre del bucket en la política coincida con `$BUCKET`.

### Verificar

Por capas, de adentro hacia afuera:

| Capa | Prueba | Resultado esperado |
| --- | --- | --- |
| EC2 (Session Manager) | `curl -s http://localhost:8000/api/info` | JSON con `"base_datos_disponible": true` |
| Target group | `backend-tg` → Targets | Todas **healthy** |
| CloudFront → API | `https://dxxxx.cloudfront.net/api/health` | `OK` |
| CloudFront → API | `https://dxxxx.cloudfront.net/api/info` | JSON; el `instance_id` cambia al recargar |
| CloudFront → S3 | `https://dxxxx.cloudfront.net` | La app lista, crea, edita y elimina productos |

### Problemas comunes

| Síntoma | Causa |
| --- | --- |
| ALB responde **504** y targets `Target.Timeout` | Target group en un puerto distinto de 8000, o `backend-sg` sin entrada 8000 desde `alb-sg` |
| Targets *unhealthy* con 404 | Health check en una ruta distinta de `/api/health` |
| CloudFront `/api/*` responde **403** | La cabecera `X-Origen-Curso` del origen no coincide con la regla del ALB |
| CloudFront `/api/*` responde **502** | Origen ALB configurado en HTTPS en lugar de HTTP only |
| CloudFront responde **Access Denied** (XML de S3) | La ruta no empieza por `/api/` y el archivo no existe en el bucket, el bucket está vacío, o falta la política del OAC. Con el OAC, S3 responde 403 (no 404) para objetos inexistentes |
| `https://dxxxx.cloudfront.net/` da 403 con `index.html` subido | Falta *Default root object* = `index.html` |
| `/api/info` con `instance_id: null` o DynamoDB sin credenciales | Hop limit de metadatos distinto de 2, o instancia sin `backend-rol` |
| Error de conexión a la base | `rds-sg` sin entrada 3306 desde `backend-sg`, o `DB_HOST` incorrecto |
| La instancia no aparece en Session Manager | Sin `backend-rol` o sin `AmazonSSMManagedInstanceCore` |

### Actualizar backend o `.env`

Las instancias del Auto Scaling Group no ven los cambios hechos en `backend-base`. Para publicar un cambio:

1. Encender `backend-base`, aplicar el cambio (`git pull` y `bash scripts/deploy-backend.sh`, o editar `.env` y `--solo-reiniciar`) y verificar.
2. Crear una AMI nueva (`backend-ami-v2`).
3. `backend-lt` → Actions → **Modify template (Create new version)** con la nueva AMI.
4. `backend-asg` → Instance refresh → **Start instance refresh**.

## Limpieza

Eliminar, en este orden: CloudFront (deshabilitar y borrar), bucket S3 (vaciar y borrar), `backend-asg`, `backend-alb`, `backend-tg`, `backend-lt`, AMIs y sus snapshots, `backend-base`, RDS, tabla DynamoDB, `backend-rol` y los grupos de seguridad `rds-sg`, `backend-sg` y `alb-sg`.
