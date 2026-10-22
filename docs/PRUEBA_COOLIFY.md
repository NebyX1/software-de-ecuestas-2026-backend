# Verificación de despliegue — 22/10/2026

## Configuración vigente

El frontend utiliza únicamente:

```dotenv
VITE_API_URL=https://mapi.uypolls.online
```

Esta variable se incorpora durante el build. El frontend se publica en `https://uypolls.online` y Axios conecta directamente con la API, con credenciales. Nginx sirve archivos estáticos y deriva su política CSP de la misma variable. No se configura conexión privada del frontend al backend.

El backend permite el origen exacto `https://uypolls.online` mediante CORS. Cada POST exige un token CSRF válido ligado a su cookie de sesión y, por HTTPS, una referencia autorizada. Los formularios administrativos conservan el requisito de referencia del propio backend. Las cookies se mantienen en el host del backend, sin ampliar su atributo Domain.

La configuración opcional de Turnstile reside en el backend. Su clave pública se entrega mediante `/api/csrf`; la clave secreta nunca se incluye en el frontend.

## Pruebas ejecutadas con esta conexión

- **108 pruebas de frontend**, ESLint y compilación TypeScript/Vite.
- **1.683 pruebas de backend aprobadas** y 7 integraciones omitidas por no configurar su fixture externo. Las pruebas siguientes sí usan MariaDB y Redis reales en Docker.
- **35 recorridos de navegador por HTTP**, incluidos los caminos condicionales de la encuesta, bloqueo de enlaces copiados, errores de red, simulación, CSV y administración.
- **4 recorridos por HTTPS entre orígenes distintos**, con frontend en `https://localhost:8443` y API en `https://localhost:8444`. Se verificaron encuesta, simulación y descarga del CSV sin escribir respuestas simuladas en MariaDB.
- **52 respuestas reales del entorno de pruebas**, 38 gráficas verificadas, filtros, paginación y ocho descargas CSV, con frontend y backend separados por origen HTTPS.
- **Escenario en modo production aprobado**: MariaDB con conector nativo, Redis, SMTP STARTTLS con certificado verificado, cookies Secure/HttpOnly/SameSite=Lax, CORS autorizado y denegado, rechazo sin CSRF o referencia HTTPS, mínimo de 15 segundos, guardado, reintento idempotente, acceso administrativo con código de correo, gráficas y CSV.
- **Imagen independiente del frontend construida con la URL final**: `VITE_API_URL=https://mapi.uypolls.online`. Su Nginx pasó la validación de configuración sin acceso a ninguna red ni backend.
- Cuestionario original preservado: 116 opciones/áreas, 14 preguntas literales y cuatro límites.

Las pruebas de CSRF incluyen solicitudes a `mapi.uypolls.online` desde `uypolls.online`, cookies ligadas a la sesión, dominios ajenos, origen null, esquema/puerto incorrectos y administración con referencia ajena.

## Alcance

Estas comprobaciones se ejecutaron localmente. No constituyen un despliegue en el servidor de Coolify ni una validación de sus certificados públicos o de la entrega de su proveedor SMTP. Los certificados HTTPS y SMTP de las pruebas son temporales y quedan en `artifacts/`, fuera de Git.

Los archivos privados `.env.coolify` están excluidos de Git, imágenes y ZIP. El frontend contiene una sola variable. Los campos SMTP y las conexiones reales de MariaDB/Redis permanecen pendientes en el backend según lo indicado por el responsable.

La guía `COOLIFY.md` contiene la configuración actual. `tests/e2e/production/` y `compose.production-test.yaml` reproducen la prueba local de producción. Los fixtures de producción limpian sus propios registros al finalizar; la simulación se deshabilita al terminar sus pruebas.
