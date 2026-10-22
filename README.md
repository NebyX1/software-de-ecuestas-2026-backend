# Backend de gestión de encuestas

Backend Flask modular basado en la estructura de [buzon-ciudadano-backend](https://github.com/IntendenciaDeLavalleja/buzon-ciudadano-backend): factoría, blueprints públicos y administrativos, SQLAlchemy, Flask-Migrate, Marshmallow, WTForms, Argon2, Flask-Login, correo y Redis. Las funciones del buzón que corresponden a denuncias, mapas, archivos MinIO y agenda no se incluyen porque no forman parte de la encuesta.

## Configuración y ejecución

Requiere Python 3.11 o 3.12, MariaDB con InnoDB, Redis y SMTP. El Dockerfile incluye el conector nativo `mariadb` y usa `requirements.lock` con dependencias directas y transitivas fijadas para Python 3.11/Linux. Copiar `.env.example` a `.env`, generar secretos independientes de al menos 32 caracteres y completar la configuración.

```sh
python -m venv .venv
# Activar el entorno de Python según el sistema operativo.
python -m pip install -r requirements.txt
python -m flask --app wsgi:app db upgrade -d migrations
python -m flask create-admin nombre correo@example.org contraseña-de-12-o-mas-caracteres true
python wsgi.py
```

La variante `create-admin nombre correo@example.org` solicita la contraseña oculta y crea un admin normal; añadir `--superuser` crea un superadmin con el mismo prompt seguro. La interfaz tradicional de cuatro argumentos se conserva en [instructions.txt](instructions.txt). No guardar contraseñas reales en scripts ni historial compartido.

`FLASK_CONFIG=production` exige MariaDB, secretos independientes, Redis, SMTP con TLS/SSL, orígenes HTTPS explícitos y hosts permitidos. La participación pública utiliza un número verificador propio almacenado en Redis, de un solo uso y con intentos y vencimiento limitados; no requiere proveedores externos ni envía SMS. Turnstile es una capa adicional opcional: solo configurar sus credenciales si se activa `TURNSTILE_REQUIRED=true`. La verificación administrativa por correo permanece obligatoria.

En la carpeta de trabajo completa se preparó `.env.coolify` con dos claves aleatorias independientes, para importar como variables solo de runtime. El backend se publica en `https://mapi.uypolls.online`, con el panel en `/admin/login`. `FRONTEND_URL` y CORS conservan `https://uypolls.online`; los hosts permitidos incluyen los dos dominios. La encuesta usa su proxy `/api` y los contenedores se comunican por red privada. Las bases y el SMTP quedan pendientes por indicación del responsable. Ese archivo es privado y está excluido de Git, ZIP e imágenes. `.env.example` conserva el inventario sin secretos. La plantilla activa la migración inicial mediante `RUN_MIGRATIONS=true`; usar una sola instancia y separar las migraciones antes de escalar. La guía completa está en `docs/COOLIFY.md` dentro de las exportaciones.

## Estructura

- `app/routes/public`: API JSON de participación, protegida con CSRF.
- `app/routes/admin`: administración renderizada en el backend, con CSRF y sesiones.
- `app/models`: usuarios, desafíos de correo, auditoría, invitaciones, respuestas y proyección de variables.
- `app/schemas`: Marshmallow y catálogo exacto de opciones del formulario original.
- `app/services`: envío de correo, verificador local, antibot, control de participación y analítica.
- `app/repositories`: acceso a datos y restricciones de unicidad.
- `app/forms`: formularios administrativos WTForms.
- `migrations`: esquema versionado y reversible. No ejecutar `db.create_all()` en producción.
- `public`: CSS local de administración; no depende de CDNs ni scripts externos.

## Rutas y flujos

Se conservan `/admin/login`, `/admin/2fa`, `/admin/dashboard`, `/admin/users`, `/admin/users/<id>/edit`, `/admin/users/<id>/delete`, `/admin/logs` y `/admin/logs/export`. El login pide correo, contraseña y un número verificador aritmético, seguido de un código de seis dígitos enviado por correo. El código está hasheado, vence a los diez minutos, admite cinco intentos y se consume bajo bloqueo transaccional. Un nuevo acceso invalida el código anterior. Nunca se escribe el código en los logs. La baja, cambio de credenciales o rol revoca sesiones y códigos pendientes.

El cierre de sesión conserva `/admin/logout` pero usa POST con CSRF. Cada sesión de acceso tiene un nonce en Redis con vencimiento absoluto de cuatro horas; cerrar sesión lo revoca, de modo que una copia anterior de la cookie tampoco puede reutilizarse. Las bajas de usuarios son desactivaciones para conservar la auditoría; siempre debe quedar al menos un superadmin activo. Los administradores comunes consultan respuestas y analítica; solo un superadmin gestiona usuarios y auditoría.

`/admin/dashboard` muestra distribuciones con gráficos SVG y tablas accesibles para todas las variables categóricas, filtros combinables y una serie diaria. Las fechas de filtros incluyen días completos de Uruguay. Las preguntas condicionales usan como denominador quienes las respondieron; las selecciones múltiples pueden sumar más del 100%. `/admin/responses` lista respuestas paginadas; `/admin/responses/export.csv` exporta la selección actual, con UTF-8 BOM y neutralización de fórmulas de planilla. No exporta teléfono, IP, cookie, identificador de dispositivo, ni tokens.

API pública:

Las respuestas incorporan metadatos descriptivos del dispositivo, sistema operativo, navegador y aplicación de acceso, además de marca/modelo cuando están disponibles, idioma, zona horaria, pantalla y ventana. Se consultan en el detalle, en cuatro gráficos adicionales y mediante filtros combinables; el CSV agrega columnas `technical_*`. El campo opcional `clientMetadata` tiene validación estricta; no se confía en él para identidad ni unicidad. La detección no guarda el User-Agent completo. La migración `9a7e3c2d1f60` conserva los registros anteriores como «sin registro». Ver `docs/DISPOSITIVOS.md` en los paquetes exportados.

| Método | Ruta | Función |
|---|---|---|
| GET | `/api/csrf` | Token de CSRF de la sesión para `X-CSRFToken` |
| POST | `/api/survey/links` | Crear invitación ligada al navegador; Turnstile solo si se activa |
| POST | `/api/survey/session` | Validar propiedad, vigencia y estado del enlace |
| POST | `/api/survey/challenge` | Emitir verificador local ligado a la invitación y al navegador |
| POST | `/api/survey/responses` | Consumir el verificador y registrar de forma transaccional e idempotente |

Los errores JSON tienen `{ "error": "mensaje", "code": "codigo" }` y opcionalmente `details`. No se expone el detalle de errores SQL, claves o respuestas en los logs.

Las condiciones de localidad, pertenencia y evaluación municipal se validan juntas en el servidor. Minas y localidad Ns/Nc no admiten bloque municipal; las seis localidades municipales determinan su propio municipio. «Otra zona urbana/rural» exige declarar pertenencia y solo evalúa el municipio seleccionado, cuando corresponde. El servidor rechaza campos dependientes incompatibles antes de consumir el desafío o guardar respuestas. La matriz compartida de 1.446 casos compara estas reglas con Zod. Ver `docs/LOGICA_ENCUESTA.md` en los paquetes exportados.

## Coolify y redes

Cada carpeta `backend/` y `frontend/` se puede publicar como repositorio independiente. Para este backend seleccionar Dockerfile, puerto `5000`, health check `/health/ready` y copiar las variables de `.env.example`. El frontend suministrado hace proxy de `/api`, `/admin` y `/public` para mantener cookies y CSRF en el mismo origen. MariaDB y Redis deben estar en red privada; no exponer sus puertos públicamente. El proxy de Coolify debe servir HTTPS.

`TRUSTED_PROXY_COUNT` debe coincidir con los proxies que realmente fijan `X-Forwarded-For` y `X-Forwarded-Proto`. El nginx incluido sobrescribe esos valores; usar `1` entre nginx y Flask, y aislar el backend para que no pueda recibirse tráfico directo con cabeceras falsificadas. Si se expone el backend directamente mediante otra cadena de proxies, ajustar y verificar la IP percibida antes de lanzar publicidad. `TRUSTED_HOSTS` incluye los nombres reales de frontend, backend y hosts usados en health checks. No usar comodines de CORS.

Aplicar migraciones una sola vez como tarea de release antes de iniciar/escalar. Para el primer contenedor único se puede usar `RUN_MIGRATIONS=true`; luego dejar `false` y migrar desde una tarea dedicada. `/health/ready` comprueba conexión a DB, revisión de migraciones y Redis; `/health/live` comprueba el proceso. No hay fallback de Redis a memoria en producción. SMTP tiene timeout y validación de certificados TLS.

## Datos y controles de participación

Los controles se combinan: verificador aritmético local de un solo uso, campo señuelo, tiempo mínimo de llenado, token aleatorio de un solo uso, cookie firmada HttpOnly, UUID local, normalización y unicidad del celular declarado, HMAC de IP y límites distribuidos en Redis. El verificador vence a los cinco minutos y admite hasta cinco intentos. En producción el tiempo mínimo de llenado es de 15 segundos (`SURVEY_MIN_FILL_SECONDS`). Las restricciones SQL únicas protegen envíos simultáneos. Los datos identificatorios se guardan como HMAC por encuesta en una tabla separada, sin clave foránea a las opiniones. Esa separación reduce exposición; los timestamps y acceso privilegiado aún pueden permitir inferencias, por lo que no se promete anonimato absoluto.

La IP se usa como señal y límite de frecuencia; `SURVEY_ENFORCE_IP_UNIQUENESS=false` viene seleccionado para permitir distintas personas de una misma red. `SURVEY_LINK_IP_LIMIT`, `SURVEY_CHALLENGE_IP_LIMIT` y `SURVEY_RESPONSE_IP_LIMIT` permiten ajustar los límites compartidos según el tráfico. Permanece el bloqueo por teléfono declarado y navegador. El formato del celular no prueba que la persona sea su titular: sin SMS no se verifica su posesión y alguien podría declarar un número ajeno. El bloqueo estricto por IP se puede activar explícitamente, asumiendo que excluirá a otras personas de la conexión. VPN, borrado de almacenamiento, perfiles privados y otro teléfono pueden eludir señales de dispositivo. No existe garantía de una persona por respuesta sin un identificador o padrón externo.

`IDENTITY_HMAC_KEY` debe mantenerse estable durante el estudio para que los bloqueos sigan siendo comparables. Rotar `SECRET_KEY` revoca sesiones y cookies de borradores, pero no los bloqueos si se conserva el HMAC. Ejecutar diariamente `flask cleanup-survey` para eliminar invitaciones vencidas; los verificadores se eliminan automáticamente por TTL de Redis. Definir la retención y eliminación final del estudio antes del lanzamiento; no conservar indefinidamente datos de participación por defecto operativo.

La migración `4d38b91e66a2` elimina seis columnas transitorias de SMS de la versión previa, sin modificar opiniones ni la evidencia durable de duplicados. Ejecutar las migraciones existentes antes de publicar esta versión sobre una instalación anterior.

## Simulación privada del formulario

En el panel, **Simular** permite habilitar, reiniciar y deshabilitar `/simular` en el frontend. El formulario de prueba solicita correo y contraseña de un administrador activo. Este acceso solo autoriza la simulación y no inicia una sesión de administración ni reemplaza el doble factor por correo del panel.

La configuración de habilitación, la generación y los accesos revocables duran en Redis; los accesos vencen a las cuatro horas. Reiniciar o deshabilitar invalida los accesos anteriores. Cambiar la contraseña o desactivar la cuenta también revoca su acceso. El frontend comprueba el estado cada cinco segundos y al volver a la pestaña; cada operación de prueba lo valida nuevamente en el servidor.

Las respuestas de prueba no se guardan en MariaDB, Redis ni en almacenamiento del navegador. Permanecen en memoria en la pestaña; se envían a `/api/simulation/export.csv` solo para validar y generar el CSV de ejemplo. El celular se valida por formato y se descarta, sin reclamar unicidad. El CSV usa las mismas columnas, escape de fórmulas, UTF-8 con BOM y reglas condicionales que la exportación real; cada fila de prueba lleva un ID que comienza con `SIMULACION-`. Los verificadores aritméticos tienen un espacio de claves Redis separado y expiran automáticamente. No hay listado ni analítica de simulaciones. Recargar, salir o reiniciar descarta el progreso y el archivo en memoria; descargarlo antes.

No requiere migraciones ni nuevas variables de entorno. La URL del acceso de prueba se deriva de `FRONTEND_URL` y las llamadas usan el proxy del frontend para conservar cookies y CSRF en el mismo origen.

## Verificación

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m pip_audit --no-deps --disable-pip -r requirements.lock --ignore-vuln PYSEC-2026-217
```

Los tests unitarios usan SQLite/fakeredis. Los de integración con MariaDB/Redis requieren la configuración de pruebas indicada en el `compose.yaml` del proyecto y verifican carreras de concurrencia reales. Antes de producción comprobar por HTTPS el envío y consumo real de correo administrativo, el verificador local, proxy/IP, backups y restauración; probar Turnstile únicamente si se activa. Las pruebas unitarias no sustituyen esa verificación operativa.

La única excepción de auditoría corresponde a una diferencia entre el paquete Python y la biblioteca C enlazada. La imagen exige Connector/C corregido en build y en producción; consultar [SECURITY_AUDIT.md](SECURITY_AUDIT.md) para el aviso, la versión verificada y la justificación. Otras alertas continúan haciendo fallar la auditoría.
