# Despliegue en Coolify desde dos repositorios

## Contenido para GitHub

`frontend/` y `backend/` son proyectos independientes. Cada uno incluye su Dockerfile, dependencias, ejemplo de variables y documentación. Se pueden subir los contenidos de cada carpeta a la raíz de su correspondiente repositorio. No crear repositorios anidados dentro de esta carpeta de trabajo.

Desde PowerShell, `./scripts/export-repositories.ps1` genera dos ZIP en `artifacts/` excluyendo secretos, Git, dependencias, builds y cachés. Los ZIP incluyen estas guías. Descomprimir cada uno en una carpeta nueva y crear allí el repositorio Git. No se crean ni publican repositorios remotos automáticamente.

## Archivos privados preparados

En esta carpeta de trabajo se generaron `backend/.env.coolify` y `frontend/.env.coolify`, listos para importar en **Environment Variables > Developer view** de cada aplicación. `SECRET_KEY` e `IDENTITY_HMAC_KEY` ya contienen claves aleatorias independientes. Estos archivos están excluidos de Git, de los ZIP y de las imágenes Docker; conservar una copia privada y no regenerar las claves durante el relevamiento.

Los dominios definidos por el responsable son **`https://uypolls.online`** para el frontend y **`https://mapi.uypolls.online`** para el backend. `FRONTEND_URL` y `CORS_ORIGINS` conservan el origen del frontend; `TRUSTED_HOSTS` incluye ambos dominios y los hosts de health checks. El hostname de Turnstile opcional sigue siendo `uypolls.online`; Turnstile permanece desactivado. Quedan pendientes los nombres/credenciales internos de MariaDB y Redis, el alias DNS privado del backend y el CIDR del proxy. Los campos del servidor, usuario, contraseña y remitente SMTP están vacíos. Los puertos y la configuración TLS de correo tienen sus valores estándar. Completar esos datos antes del primer despliegue. El backend no arranca en producción mientras falten su base o el SMTP obligatorio del acceso administrativo. El frontend rechaza los marcadores `PENDIENTE`, `localhost` como backend y una red proxy `/0`.

`node scripts/prepare-coolify-env.mjs` permite volver a crear archivos que falten sin sobrescribir ningún archivo existente ni rotar sus claves. `.env.coolify` es un archivo de importación: no reemplaza `.env.local` ni se carga automáticamente en el desarrollo local. En repositorios ya separados también se puede copiar `.env.example` y completar sus valores manualmente.

En Coolify, configurar **todas las variables del backend solo en runtime**, con Build time en **Not available during build**. En el frontend, `BACKEND_UPSTREAM` y `TRUSTED_PROXY_CIDR` son solo runtime; únicamente `VITE_TURNSTILE_SITE_KEY`, si se usa, debe estar disponible durante el build. Seleccionar **Advanced > Build > Build arguments > Managed manually in Dockerfile**. Las variables `VITE_*` se incorporan al JavaScript público.

## Red y recursos

1. Crear MariaDB 11.4 y Redis 7.4 con almacenamiento persistente en Coolify. Configurar claves propias y guardar sus URLs internas. No publicar sus puertos hacia Internet.
2. Crear una aplicación desde el repositorio del backend con build pack **Dockerfile**, contexto raíz, Dockerfile `/Dockerfile` y puerto interno **5000**. Asignar el dominio HTTPS **`https://mapi.uypolls.online`**, dirigido al puerto interno 5000, y habilitar certificado y redirección HTTP a HTTPS. Asociarla a la misma red privada que MariaDB, Redis y el frontend. Reservar además un alias DNS interno estable y exclusivo en **General > Network > Network Aliases**, por ejemplo `encuestas-backend`. El nombre visible del recurso en el panel y el registro DNS público `mapi` no crean ese alias privado.
3. Crear otra aplicación desde el repositorio del frontend con build pack **Dockerfile**, contexto raíz, Dockerfile `/Dockerfile` y puerto **8080**. Asignar el dominio público **`https://uypolls.online`**. Configurar previamente su DNS hacia el servidor de Coolify y habilitar el certificado HTTPS y la redirección desde HTTP.
4. Configurar `BACKEND_UPSTREAM=http://<alias-interno-del-backend>:5000` en el frontend, sin barra final, rutas ni consultas. El nombre debe resolverse desde su contenedor. Usar el mismo servidor y **destination network** en las dos aplicaciones y las bases. Si algún recurso es un stack Compose/Service, activar **Connect To Predefined Network** para incorporarlo a esa misma red. Estar en el mismo proyecto de Coolify no conecta por sí solo los contenedores. No usar `localhost` para referirse al otro contenedor.
5. El frontend reenvía `/api/`, `/admin/` y `/public/` al backend a través de la red privada. La encuesta usa la API bajo `uypolls.online/api/`; la administración se abre directamente en `mapi.uypolls.online/admin/login`. El acceso administrativo por `/admin` del frontend también conserva compatibilidad, con una sesión independiente para cada host. No habilitar caché de API, panel ni rutas `/s/` en un CDN o proxy adicional.

Conservar `Referrer-Policy: same-origin` tanto en Nginx como en el HTML: Flask-WTF necesita la referencia del propio sitio para verificar POST por HTTPS. Esta política no envía la referencia a otros orígenes. Los encabezados Host conservan el puerto cuando existe; no desactivar el control SSL estricto de CSRF para resolver una configuración incorrecta.

El frontend usa rutas relativas `/api`, sin `VITE_API_URL`. El backend conserva Flask-CORS con credenciales como en Buzón Ciudadano, limitado a **`https://uypolls.online`**; se validan también cookies y CSRF. `FRONTEND_URL` y `CORS_ORIGINS` contienen ese mismo origen exacto, sin `/participar`, barra final ni comodines. El subdominio `mapi` es el dominio del recurso backend, mientras que `BACKEND_UPSTREAM` sigue siendo su URL HTTP privada en Docker. No apuntar esa variable a la IP pública ni al dominio HTTPS de `mapi`: su función es el enlace interno entre contenedores.

En Coolify, ambos dominios pasan por el proxy HTTPS y sus respectivos puertos internos. No publicar directamente los puertos de MariaDB, Redis o Gunicorn en el host. La captura de DNS aportada muestra `A @ -> 152.53.90.109`, `A mapi -> 152.53.90.109` y `CNAME www -> uypolls.online`; no se ha confirmado su propagación desde el servidor. Usar `uypolls.online` como origen canónico de la encuesta. El registro `www` por sí solo no configura una redirección HTTPS ni agrega ese origen a CORS.

Las URLs previstas son `https://uypolls.online/participar` para el enlace base de Meta, `https://mapi.uypolls.online/admin/login` para administradores y `https://uypolls.online/api/csrf` para comprobar la conexión completa. `https://mapi.uypolls.online/health/ready` verifica el backend directamente. Las invitaciones usan `https://uypolls.online/s/<token>`. Los certificados y la publicación efectiva de ambos dominios siguen pendientes de configurar en Coolify.

Las cookies conservan su alcance al host que las emitió, con `Secure`, `HttpOnly` y `SameSite=Lax`. No se configura `SESSION_COOKIE_DOMAIN=.uypolls.online` ni se comparten cookies entre subdominios. Los POST administrativos de `mapi` permanecen en ese mismo origen y la encuesta mantiene sus POST en `uypolls.online` mediante el proxy. Se conserva el control SSL estricto de CSRF.

En el frontend configurar además `TRUSTED_PROXY_CIDR` con la IP (`/32`) o subred privada exacta del proxy de Coolify. Nginx usa únicamente esa fuente confiable para obtener la IP y el protocolo originales, y reenvía un solo valor normalizado al backend. El valor inicial `127.0.0.1/32` sirve para acceso local directo y **debe adaptarse al proxy real en Coolify**. Si queda mal, el bloqueo por IP puede interpretar a todos los visitantes como una sola conexión. No configurar `0.0.0.0/0`; solo permitir la red dedicada del proxy y aislar el tráfico al backend.

## Backend: variables de runtime

Usar `backend/.env.example` como inventario. No subir un `.env` real.

| Variable | Configuración |
| --- | --- |
| `FLASK_CONFIG` | `production` |
| `SECRET_KEY` | Secreto aleatorio independiente de al menos 32 caracteres |
| `IDENTITY_HMAC_KEY` | Otro secreto aleatorio estable durante todo el estudio |
| `DATABASE_URL` | `mariadb+mariadbconnector://usuario:clave@host:3306/base`; codificar caracteres reservados de usuario/clave como URL |
| `REDIS_URL` | URL interna autenticada `redis://:clave@host:6379/0` o TLS cuando corresponda |
| `FRONTEND_URL` | URL HTTPS pública sin barra final |
| `CORS_ORIGINS` | Origen público exacto, sin comodines |
| `TRUSTED_HOSTS` | `uypolls.online,mapi.uypolls.online,localhost,127.0.0.1`, **sin `https://`, rutas ni puerto** |
| `TRUSTED_PROXY_COUNT` | `1` con el Nginx suministrado que normaliza los encabezados de cliente; revisar si se modifica la topología |
| `MAIL_*` | SMTP real, remitente autorizado y TLS o SSL; no activar supresión de correo |
| `SURVEY_ID` | `lavalleja-2026`; no cambiar durante el trabajo de campo |
| `SURVEY_ENFORCE_IP_UNIQUENESS` | `false`, política elegida: IP como señal y límite de frecuencia |
| `SURVEY_LINK_IP_LIMIT`, `SURVEY_CHALLENGE_IP_LIMIT` | Límites Redis por IP para enlaces y verificadores locales; revisar tráfico de redes compartidas |
| `SURVEY_MIN_FILL_SECONDS` | Tiempo mínimo de participación validado en servidor; 15 segundos por defecto en producción |
| `TURNSTILE_REQUIRED` | `false` por defecto; capa opcional adicional |
| `TURNSTILE_SECRET_KEY` | Clave privada solo si se activa el widget opcional |
| `TURNSTILE_HOSTNAME` | Host público, sin `https://` ni rutas |
| `RUN_MIGRATIONS` | `true` solo para la instancia única del despliegue inicial o un job de migración; luego `false` al escalar |

Los secretos del backend son variables de runtime. No se pasan como argumentos de build del frontend. Mantener copias protegidas de las claves junto con el procedimiento de restauración.

## Frontend: build y runtime

El verificador local funciona sin claves ni proveedores. Si se activa la capa opcional Turnstile, en build `VITE_TURNSTILE_SITE_KEY` debe ser la clave pública del mismo widget que valida el backend. Cambiarla requiere reconstruir el frontend. El widget debe permitir el dominio definitivo y emitir la acción `survey_start`.

En runtime, `BACKEND_UPSTREAM` apunta al backend en la red privada. La política CSP permite los recursos de Turnstile y el propio sitio. No necesita un dominio externo de API en el navegador.

## Migración inicial y administradores

Primero respaldar la base si ya tiene datos. Ejecutar una sola vez, desde el contenedor del backend o un job conectado a la misma configuración:

```sh
python -m flask --app wsgi:app db upgrade -d migrations
python -m flask --app wsgi:app seed-data
python -m flask --app wsgi:app create-admin nombre correo@dominio.uy --superuser
```

El comando solicita y confirma la contraseña mediante entrada oculta. También se conserva la interfaz de cuatro argumentos de la referencia, documentada en `backend/instructions.txt`; evitar contraseñas en argumentos cuando puedan quedar en el historial.

En una instancia inicial también se puede configurar `RUN_MIGRATIONS=true` para que el entrypoint migre antes de iniciar Gunicorn. No lanzar varias réplicas migrando simultáneamente. Al escalar, separar la migración como paso de publicación y dejar `RUN_MIGRATIONS=false` en las réplicas.

La plantilla y los archivos privados preparados usan `RUN_MIGRATIONS=true` para esa primera instancia. Coolify omite el comando pre-deployment cuando todavía no hay un contenedor anterior, y su post-deployment ocurre después de declarar completado el despliegue: para el primer arranque usar el entrypoint ya incluido o un job previo explícito. No dejar la creación del esquema pendiente hasta después del healthcheck.

## Health checks y verificación final

- Backend: `GET /health/live` verifica proceso; `GET /health/ready` verifica base, esquema y Redis. Coolify debe usar readiness para decidir disponibilidad. El host de su llamada debe estar permitido.
- Frontend: `GET /health` responde por Nginx; verificar además `GET /api/csrf` a través del dominio público para probar la conexión al backend.
- Entrar en `https://mapi.uypolls.online/admin/login`, resolver la suma y comprobar que la contraseña sola no abre el panel. Confirmar recepción y vencimiento del código por correo.
- Completar una encuesta de prueba en el entorno previo al lanzamiento, resolver el verificador local y confirmar guardado, aparición en dashboard y CSV sin identificadores. El celular es un dato declarado, sin comprobación de titularidad.
- Copiar la invitación a otro navegador y comprobar rechazo; volver a usar el enlace después del envío y comprobar el mensaje. Probar reintento tras desconectar la red y el bloqueo por celular, dispositivo e IP según política.
- Probar las ramas de Minas, municipio directo, otra zona, menor de edad y no residente. Probar Facebook e Instagram en Android e iOS con las cookies reales del dominio.
- Revisar HTTPS, CSP, cookies seguras, IP observada detrás del proxy, límites Redis, backups y logs sin cuerpos ni tokens. Deshabilitar grabaciones de sesión y no incluir píxel publicitario en las respuestas.

Las pruebas con SMTP administrativo y navegadores internos de Meta requieren la configuración del operador. La participación no depende de un proveedor de mensajería.

Ambos Dockerfiles ya incluyen un `HEALTHCHECK` ejecutable: Python en backend y `wget` en frontend. En aplicaciones Dockerfile, Coolify da prioridad al healthcheck de la imagen sobre el definido en el panel. No hace falta instalar `curl` en el backend ni reemplazar su check. `/health/ready` pertenece al backend; en el dominio del frontend esa ruta no es un check de base de datos. La comprobación pública entre las dos aplicaciones es `/api/csrf`.

## Prueba local del modo producción

Se verificó el modo `production` de las imágenes con HTTPS, cookies `Secure`/`HttpOnly`/`SameSite=Lax`, CSRF SSL estricto, preflight CORS autorizado y rechazado, tiempo mínimo de 15 segundos, envío y reintento idempotente, ingreso administrativo con correo STARTTLS y certificado verificado, 38 gráficas y CSV. También se cambió realmente la IP del backend y se comprobó que el frontend conservaba su contenedor y recuperaba `/api/csrf` mediante DNS, sin reiniciarlo.

Para reproducir desde la carpeta de trabajo completa, con `.env.local`, `.env.e2e` y los servicios locales preparados:

```sh
node scripts/prepare-production-test.mjs
docker compose --env-file .env.local --env-file .env.e2e -f compose.yaml -f compose.tls-test.yaml -f compose.production-test.yaml up -d --build --wait
npm run test:production --prefix tests/e2e
node scripts/verify-backend-redeploy.mjs
```

Estos archivos Compose son exclusivamente de pruebas locales. Los certificados temporales quedan en `artifacts/`; la confianza del certificado SMTP se incorpora solo al contenedor de prueba, sin desactivar la validación TLS. La prueba de navegador acepta únicamente su certificado HTTPS local autofirmado. Los fixtures usan un identificador de relevamiento reservado y limpian sus propios registros. No usan el futuro SMTP ni el dominio público del estudio. Los reportes se guardan en `artifacts/coolify-production-verification.json` y `artifacts/coolify-redeploy-verification.json`.

## Backups, cambios y mantenimiento

Configurar backups automáticos cifrados de MariaDB en Coolify. Respaldar también los secretos por un canal seguro. Redis conserva límites temporales; MariaDB conserva invitaciones y evidencia durable de unicidad. Restaurar todas las tablas del relevamiento, no solamente opiniones.

Antes de cada versión: backup, pruebas sobre una copia, migración revisada y despliegue con health checks. Un rollback de imagen no revierte automáticamente una migración. Evitar cambios incompatibles de esquema sin estrategia de compatibilidad.

Programar `python -m flask --app wsgi:app cleanup-survey` diariamente para eliminar invitaciones expiradas; conserva evidencia de duplicados. Los verificadores Redis vencen automáticamente. Definir la retención final con el responsable del estudio y revisar permisos, disponibilidad y alertas de correo administrativo.

Documentación oficial consultada el 22/10/2026: [Dockerfile](https://coolify.io/docs/applications/builds/dockerfile), [variables y alcance build/runtime](https://coolify.io/docs/applications/configuration/environment-variables), [redes](https://coolify.io/docs/core/networking-in-coolify), [red predefinida de Services](https://coolify.io/docs/services/configuration/networking), [health checks](https://coolify.io/docs/applications/configuration/health-checks) y [SMTP STARTTLS de Mailpit para la prueba local](https://mailpit.axllent.org/docs/configuration/smtp/).
