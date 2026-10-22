# Despliegue en Coolify desde dos repositorios

## Frontend

Repositorio: `NebyX1/software-de-ecuestas-2026-frontend`. Elegir Dockerfile, contexto raíz, puerto interno **8080**, dominio **https://uypolls.online** y healthcheck **/health**.

Configurar una sola variable, disponible durante el build:

```dotenv
VITE_API_URL=https://mapi.uypolls.online
```

El Dockerfile declara ese argumento. Al cambiar la URL, reconstruir la imagen. No se necesitan variables de runtime, alias Docker del backend ni CIDR del proxy en el frontend. Nginx sirve la aplicación estática y el navegador se comunica directamente con la API mediante Axios con credenciales, como en Buzón Ciudadano.

## Backend

Repositorio: `NebyX1/software-de-ecuestas-2026-backend`. Elegir Dockerfile, contexto raíz, puerto interno **5000**, dominio **https://mapi.uypolls.online** y healthcheck **/health/ready**.

Importar las variables de `backend/.env.coolify` como variables de **runtime**. El archivo es privado y está excluido de Git, imágenes y ZIP. Las claves aleatorias ya generadas se conservan. Completar las URLs privadas de MariaDB y Redis y los campos SMTP. El backend requiere SMTP para el acceso administrativo con código por correo.

La conexión pública queda configurada así:

```dotenv
FRONTEND_URL=https://uypolls.online
CORS_ORIGINS=https://uypolls.online
TRUSTED_HOSTS=uypolls.online,mapi.uypolls.online,localhost,127.0.0.1
TRUSTED_PROXY_COUNT=1
```

MariaDB y Redis deben compartir red privada con el backend y mantener sus volúmenes. No publicar sus puertos. El frontend puede desplegarse por separado y se conecta por la URL HTTPS pública; no necesita acceder a esa red.

Los dos dominios deben contar con certificado HTTPS y redirección desde HTTP. El proxy de Coolify entrega la IP y el protocolo de la solicitud al backend. `TRUSTED_PROXY_COUNT=1` corresponde a ese único proxy; el puerto de Gunicorn debe recibir tráfico público únicamente mediante Coolify.

## CORS, cookies y CSRF

El origen autorizado es exactamente **https://uypolls.online**, sin rutas, barra final ni comodines. Axios envía las cookies con `withCredentials: true` y CORS admite credenciales únicamente para los orígenes configurados.

Las cookies se emiten para el host del backend, con `Secure`, `HttpOnly` y `SameSite=Lax`. Los subdominios HTTPS de `uypolls.online` pertenecen al mismo sitio; no se requiere `SESSION_COOKIE_DOMAIN` ni cookies con `SameSite=None`. El frontend usa `Referrer-Policy: strict-origin` para enviar solo su origen, nunca la ruta de una invitación.

Cada POST de la API exige un token CSRF ligado a la sesión y valida el origen y la referencia HTTPS contra los orígenes autorizados. Los formularios administrativos mantienen la comprobación del propio origen del backend. No desactivar CSRF para corregir CORS.

La campaña abre **https://uypolls.online/participar**, el panel **https://mapi.uypolls.online/admin/login** y la simulación **https://uypolls.online/simular**. La comprobación de API es **https://mapi.uypolls.online/api/csrf**.

## Archivos de configuración

`frontend/.env.example` y el archivo privado `frontend/.env.coolify` contienen únicamente `VITE_API_URL`. `node scripts/prepare-coolify-env.mjs` crea los archivos privados que falten y conserva las claves existentes. Los campos de bases y correo se completan en el backend.

`./scripts/export-repositories.ps1` genera dos ZIP independientes en `artifacts/`, excluyendo secretos y dependencias. También se pueden publicar directamente los contenidos de `frontend/` y `backend/` en sus repositorios.

## Variables del backend

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
| `TRUSTED_PROXY_COUNT` | `1` con el proxy HTTPS de Coolify delante del backend |
| `MAIL_*` | SMTP real, remitente autorizado y TLS o SSL; no activar supresión de correo |
| `SURVEY_ID` | `lavalleja-2026`; no cambiar durante el trabajo de campo |
| `SURVEY_ENFORCE_IP_UNIQUENESS` | `false`, política elegida: IP como señal y límite de frecuencia |
| `SURVEY_LINK_IP_LIMIT`, `SURVEY_CHALLENGE_IP_LIMIT` | Límites Redis por IP para enlaces y verificadores locales; revisar tráfico de redes compartidas |
| `SURVEY_MIN_FILL_SECONDS` | Tiempo mínimo de participación validado en servidor; 15 segundos por defecto en producción |
| `TURNSTILE_REQUIRED` | `false` por defecto; capa opcional adicional |
| `TURNSTILE_SITE_KEY` | Clave pública del widget opcional, entregada por la API al frontend |
| `TURNSTILE_SECRET_KEY` | Clave privada solo si se activa el widget opcional |
| `TURNSTILE_HOSTNAME` | Host público, sin `https://` ni rutas |
| `RUN_MIGRATIONS` | `true` solo para la instancia única del despliegue inicial o un job de migración; luego `false` al escalar |

Los secretos del backend son variables de runtime. No se pasan como argumentos de build del frontend. Mantener copias protegidas de las claves junto con el procedimiento de restauración.

## Verificación de participación

El verificador numérico propio permanece activo sin proveedores externos. Turnstile es opcional y está desactivado por defecto. Para activarlo, configurar `TURNSTILE_REQUIRED`, `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY` y `TURNSTILE_HOSTNAME` únicamente en el backend. `GET /api/csrf` entrega su clave pública; la clave secreta nunca se publica ni se incorpora al frontend.

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

## Diagnóstico de correo y doble factor

Desde la terminal del contenedor del **backend en producción**, ejecutar:

```sh
python -m flask --app wsgi:app check-mail
```

El comando usa las variables efectivas de ese proceso y el mismo transporte SMTP que el doble factor. Comprueba conexión, certificado TLS y autenticación sin enviar correo. Una prueba desde otra máquina no comprueba la salida de red, DNS ni certificados del contenedor. Para SSL implícito en el puerto 465, usar `MAIL_USE_SSL=true` y `MAIL_USE_TLS=false`; para STARTTLS, configurar el puerto indicado por el proveedor y `MAIL_USE_TLS=true`, `MAIL_USE_SSL=false`. `MAIL_TIMEOUT` permite ajustar el timeout por operación de socket (10 segundos por defecto). No desactivar la validación del certificado para resolver errores TLS.

Los fallos del acceso administrativo se escriben en stderr como JSON con `event=admin_otp_delivery_failed`; los del comando, con `event=smtp_check_failed`. Incluyen `request_id` (coincide con la cabecera `X-Request-ID` de la respuesta), `user_id` cuando corresponde, host/puerto SMTP, SSL/STARTTLS, timeout, presencia de autenticación/remitente, etapa, clase de excepción, código SMTP y estado ampliado cuando existen. `trace` conserva archivos, funciones y líneas sin mensajes de excepción ni variables locales. No se registran contraseñas, destinatarios, cuerpos, códigos de acceso ni respuestas SMTP completas.

| Campo `reason` | Qué revisar desde el contenedor |
|---|---|
| `dns_failed` | Resolución del host SMTP. |
| `connection_timeout`, `connection_refused`, `network_failed` | Puerto, firewall y salida SMTP del servidor/proveedor de hosting. |
| `tls_certificate_invalid`, `tls_failed` | Nombre del host, certificado/cadena CA y modalidad SSL/STARTTLS. |
| `authentication_rejected` | Código SMTP, credenciales y permisos de autenticación de la cuenta. |
| `sender_rejected`, `recipient_rejected`, `message_rejected` | Código SMTP y restricciones del remitente/destinatario o política del proveedor. |
| `greeting_rejected`, `smtp_feature_unsupported`, `connection_closed` | Política SMTP/EHLO y capacidades del servidor. |
| `unexpected_error` | Clase de excepción y archivos/líneas en `trace`. |

Un error de `QUIT` después de aceptar el mensaje genera `event=smtp_disconnect_failed` en nivel WARNING y no invalida el código enviado. Si el envío falla, el acceso sigue respondiendo 503 y el desafío queda invalidado. La aceptación SMTP no confirma la llegada a la bandeja final; esa entrega se revisa con los logs del proveedor y la carpeta de correo no deseado.

## Health checks y verificación final

- Backend: `GET /health/live` verifica proceso; `GET /health/ready` verifica base, esquema y Redis. Coolify debe usar readiness para decidir disponibilidad. El host de su llamada debe estar permitido.
- Frontend: `GET https://uypolls.online/health` responde por Nginx. La API se comprueba en `https://mapi.uypolls.online/api/csrf` y completando la encuesta en el navegador.
- Entrar en `https://mapi.uypolls.online/admin/login`, resolver la suma y comprobar que la contraseña sola no abre el panel. Confirmar recepción y vencimiento del código por correo.
- Completar una encuesta de prueba en el entorno previo al lanzamiento, resolver el verificador local y confirmar guardado, aparición en dashboard y CSV sin identificadores. El celular es un dato declarado, sin comprobación de titularidad.
- Copiar la invitación a otro navegador y comprobar rechazo; volver a usar el enlace después del envío y comprobar el mensaje. Probar reintento tras desconectar la red y el bloqueo por celular, dispositivo e IP según política.
- Probar las ramas de Minas, municipio directo, otra zona, menor de edad y no residente. Probar Facebook e Instagram en Android e iOS con las cookies reales del dominio.
- Revisar HTTPS, CSP, cookies seguras, IP observada detrás del proxy, límites Redis, backups y logs sin cuerpos ni tokens. Deshabilitar grabaciones de sesión y no incluir píxel publicitario en las respuestas.

Las pruebas con SMTP administrativo y navegadores internos de Meta requieren la configuración del operador. La participación no depende de un proveedor de mensajería.

Ambos Dockerfiles ya incluyen un `HEALTHCHECK` ejecutable: Python en backend y `wget` en frontend. En aplicaciones Dockerfile, Coolify da prioridad al healthcheck de la imagen sobre el definido en el panel. No hace falta instalar `curl` en el backend ni reemplazar su check. `/health/ready` pertenece al backend; en el dominio del frontend esa ruta no es un check de base de datos. La conexión entre ambas aplicaciones se comprueba desde el navegador mediante `https://mapi.uypolls.online/api/csrf`.

## Prueba local del modo producción

Se verificó el modo `production` de las imágenes con HTTPS, cookies `Secure`/`HttpOnly`/`SameSite=Lax`, CSRF SSL estricto, preflight CORS autorizado y rechazado, tiempo mínimo de 15 segundos, envío y reintento idempotente, ingreso administrativo con correo STARTTLS y certificado verificado, 38 gráficas y CSV. Las aplicaciones se conectan mediante la URL pública del backend; un redespliegue del backend no requiere reiniciar el frontend.

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
