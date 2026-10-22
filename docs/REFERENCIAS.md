# Referencias y decisiones de arquitectura

Fuentes leídas el 21 de octubre de 2026:

- Backend: https://github.com/IntendenciaDeLavalleja/buzon-ciudadano-backend, commit `3198d34ed3c15cee47caa33ef73e94dbfd16b6ed`.
- Frontend: https://github.com/IntendenciaDeLavalleja/buzon-ciudadano-frontend, commit `811a6a29016842e8aa6b82134fb2bd5dbcb3a576`.
- Encuesta base: este repositorio, commit `4f61599f765bcddef0bc5a00a5eca9c827420d80`.

## Backend

Se conserva la fábrica Flask, organización `app/{routes,services,repositories,schemas,models,utils}`, extensiones sin ligar a aplicación, SQLAlchemy y Flask-Migrate/Alembic, Marshmallow para API, WTForms para el panel, Flask-Login, Flask-Mail, Argon2, Flask-Limiter y Redis. MariaDB es la base de producción. El panel sigue siendo Jinja servido por el backend.

Se mantienen el blueprint público, blueprint administrativo en `/admin`, login con email/contraseña y suma verificadora, código por correo en `/admin/2fa`, dashboard, gestión de usuarios y auditoría. Se conserva la interfaz de `flask create-admin usuario email contraseña true|false` documentada en `backend/instructions.txt`.

Las rutas de tickets, adjuntos, mapas, agenda y MinIO del buzón son específicas de denuncias y se sustituyen por rutas de encuesta, respuestas y estadísticas. No se requiere almacenamiento de archivos para esta encuesta. El requisito de conservar el sistema de rutas se interpreta como conservar blueprints, prefijos administrativos y flujo de autenticación; no exponer operaciones de denuncias en un gestor de encuestas.

Correcciones deliberadas de seguridad frente a la referencia: no degradar a límites en memoria cuando falla Redis en producción; verificar CSRF en la API; consumir códigos e invitaciones de manera atómica; verificar bloqueo y caducidad de OTP; cerrar sesión mediante POST; evitar CDN en el panel y almacenar secretos fuera de Git. El captcha aritmético se conserva como verificador del login y no se considera una barrera antibot suficiente por sí solo.

## Frontend

Se conservan React, TypeScript y Vite y se adoptan la capa Axios, React Query y organización por funcionalidad de la referencia, con React Hook Form, Zod y Zustand. Se reutilizan los componentes, páginas y contenido de la encuesta de este repositorio para conservar su cuestionario y bifurcaciones.

El frontend sirve el sitio y actúa como proxy para `/api`, `/admin` y los recursos del backend. Eso mantiene el flujo bajo un mismo origen HTTPS y evita depender de cookies de terceros en los navegadores internos de Meta. Cada carpeta contiene su Dockerfile y configuración independiente.

## Control de participación

La URL base de la campaña es pública y puede compartirse. Los parámetros UTM y `fbclid` no autentican a una persona ni garantizan que venga de un anuncio. No se usa su presencia como autorización.

Se genera una invitación al comenzar expresamente la encuesta, evitando que las vistas previas y los rastreadores consuman enlaces. La invitación se liga al navegador; otro navegador no puede usarla aunque la copie antes del envío. La transacción de recepción consume la invitación y registra restricciones únicas sobre señales de participación. Un reintento del mismo envío puede recuperar su comprobante sin crear otra respuesta.

La participación no usa un proveedor de mensajería. El celular conserva su pregunta original y su unicidad se comprueba mediante HMAC, pero no se verifica titularidad. El verificador local se liga a la invitación y se guarda en Redis con caducidad, intentos limitados y consumo único; lo acompañan un campo trampa, tiempo mínimo y límites distribuidos. El dispositivo se reconoce mediante almacenamiento local y cookie del servidor; otro navegador, modo privado o eliminación de datos reduce esa señal. No se implementa fingerprint invasivo como promesa de identidad fiable.

## Fuentes técnicas consultadas

- [Cloudflare: validación de Turnstile en servidor](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/): validar en servidor, duración y uso único del desafío, comprobar hostname.
- [Coolify: Docker Compose](https://coolify.io/docs/services/configuration/docker-compose): redes entre recursos y health checks definidos en Compose.

Las versiones de referencia se registran para reproducibilidad; las dependencias finales se fijan y revisan durante la implementación. La compatibilidad se acredita con compilación y pruebas, no por copiar números de versión.
