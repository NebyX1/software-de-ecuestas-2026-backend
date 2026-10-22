# Verificación de despliegue — 22/10/2026

## Resultado y alcance

Se construyeron las dos imágenes Docker y se arrancó el backend con `FLASK_CONFIG=production`, conector nativo MariaDB, Redis y SMTP STARTTLS. El acceso de navegador se realizó por `https://localhost:8443`, mediante proxy TLS, Nginx de frontend y Gunicorn de backend. Ambos contenedores ejecutan sus procesos sin root.

Se verificó:

- Frontend y API bajo un mismo origen HTTPS, sin URL pública separada de API ni errores de CORS o contenido mixto en Chromium.
- Preflight autorizado para el origen configurado y sin permisos para otro dominio o para el mismo host con esquema HTTP.
- Rechazo de POST sin CSRF y de POST HTTPS sin Referer, conservando la protección SSL estricta de Flask-WTF.
- Cookies administrativas y de participación con `Secure`, `HttpOnly` y `SameSite=Lax`.
- Rechazo de envío antes de los 15 segundos mínimos de producción, seguido de guardado correcto y reintento idempotente sin duplicación.
- Acceso administrativo con contraseña, verificador y código de correo, usando SMTP STARTTLS con certificado y hostname verificados. El servidor de correo era Mailpit local con STARTTLS obligatorio; no se envió correo externo.
- Una respuesta real visible en las 38 gráficas y en el CSV autenticado, sin teléfono, UUID del dispositivo ni token en la exportación.
- Sustitución del contenedor del backend por otro con una IP diferente: el frontend mantuvo el mismo contenedor y volvió a resolver el backend por DNS, recuperando `/api/csrf` sin reinicio.
- Arranque del frontend bloqueado ante `localhost` como backend, marcador `PENDIENTE` o CIDR universal `/0`. Una configuración privada válida fue aceptada.
- Validación de producción que rechaza CORS vacío, comodines, rutas, credenciales, fragmentos, puertos inválidos, origen público ausente de CORS y dominio público ausente de `TRUSTED_HOSTS`.

Después de los cambios pasaron **1.637 pruebas de backend**, incluidas las integraciones con MariaDB/Redis reales, **104 pruebas de frontend**, TypeScript estricto, ESLint, la comprobación del cuestionario original y los builds. También pasó el nuevo escenario de navegador en modo producción y la prueba de cambio de IP. Las advertencias de dependencias de pruebas y anotaciones de Zod se conservan documentadas; no se describen como errores de ejecución.

Tras definir el subdominio del backend se ejecutaron **24 pruebas de configuración/despliegue**, incluidas tres nuevas para la topología de dos dominios. Se verificaron POST HTTPS con CSRF estricto en ambos hosts, rechazo del Referer del otro host, acceso al formulario administrativo, cookies seguras separadas sin atributo `Domain` y preflight en el backend autorizado únicamente para el origen del frontend. Estas comprobaciones usan el cliente Flask local; no constituyen un despliegue ni una prueba de certificados públicos en Coolify. Las 21 pruebas de despliegue anteriores ya formaban parte de las 1.637 de la última batería completa.

Los registros y el administrador creados por el escenario de producción se eliminaron dentro del relevamiento local reservado. Los escenarios previos de 52 respuestas, todas las gráficas y ocho descargas CSV, junto con la exportación nativa de 261 casos, están documentados en `PRUEBA_ANALITICA.md`.

## Configuración entregada

`backend/.env.coolify` contiene dos claves aleatorias independientes ya generadas. `frontend/.env.coolify` contiene las variables de runtime del proxy y la clave pública opcional del widget. Ambos archivos son privados: se excluyen de Git, de las exportaciones y de las imágenes Docker.

Los dominios definidos por el responsable son `https://uypolls.online` para el frontend y `https://mapi.uypolls.online` para el backend. CORS conserva únicamente el origen del frontend y `TRUSTED_HOSTS` incluye ambos. La encuesta mantiene la conexión por proxy privado y la administración se abre en `mapi`. Las URLs internas de MariaDB/Redis, alias privado del backend y CIDR del proxy quedan pendientes; los campos del proveedor SMTP quedan vacíos. Los archivos no contienen credenciales ni hosts internos inventados. Es necesario completar esos datos en Coolify antes de publicar. El acceso administrativo sigue requiriendo SMTP; dejarlo vacío impide arrancar el backend en producción.

No se desplegó en una instancia real de Coolify ni se configuraron los certificados públicos. La captura aportada por el responsable muestra los registros `A @` y `A mapi` hacia `152.53.90.109`; no se verificó su propagación. La red del servidor definitivo, los certificados públicos y la entrega del proveedor SMTP deben comprobarse allí con los datos del operador. La guía `COOLIFY.md` detalla los puertos 8080/5000, la red compartida, el alias estable, los ámbitos build/runtime, migraciones y health checks.

## Reproducción y evidencia

Seguir la sección «Prueba local del modo producción» de `COOLIFY.md`. Código en `tests/e2e/production/`, `compose.production-test.yaml` y los scripts `prepare-production-test.mjs`/`verify-backend-redeploy.mjs` de la carpeta de trabajo completa. Certificados y reportes se guardan en `artifacts/`, fuera de Git y de los ZIP:

- `coolify-production-verification.json`: comprobaciones del escenario HTTPS y SMTP.
- `coolify-redeploy-verification.json`: IP nueva de backend, frontend preservado y recuperación del endpoint.
- `coolify-production.png`: captura del panel con el registro del escenario.
