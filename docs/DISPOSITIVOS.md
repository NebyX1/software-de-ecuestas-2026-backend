# Registro técnico de las respuestas

Al guardar una respuesta se registra información descriptiva del navegador. El aviso de privacidad del formulario lo informa antes de comenzar y el frontend envía la nueva versión de aviso `2026-02`, guardada con la respuesta. La API conserva compatibilidad con `2026-01` para clientes anteriores y sus reintentos. No se necesita SMS ni otro proveedor para esta función.

| Dato | Captura |
| --- | --- |
| Tipo de dispositivo | Celular, tablet, computadora u origen desconocido |
| Marca y modelo | Cuando el navegador los informa o permite inferirlos |
| Sistema operativo y versión | Encabezado User-Agent y Client Hints disponibles |
| Navegador y versión | Detección del servidor, complementada con Client Hints |
| Aplicación de acceso | Facebook, Instagram, otro navegador integrado o navegador habitual |
| Idioma y zona horaria | Valores informados por el navegador |
| Pantalla y ventana | Ancho y alto en píxeles CSS, densidad de píxeles y puntos táctiles |
| Fuente | Método utilizado para la detección; formato de metadatos versión 1 |

Estos datos quedan asociados a la respuesta en `survey_responses.device_metadata`. Cuatro columnas con índices por encuesta permiten filtrar tipo de dispositivo, sistema operativo, navegador y aplicación de acceso. No se añaden preguntas ni se modifica el cuestionario.

El panel presenta los datos en cada detalle, muestra dispositivo y sistema operativo en el listado, agrega cuatro gráficos y permite combinar esos filtros con las variables de encuesta y fechas. El CSV protegido incluye columnas `technical_*`; conserva el escape de fórmulas. No exporta UUID local, cookie, teléfono, IP ni sus HMAC. Los datos técnicos también pueden contribuir a correlacionar personas: limitar el acceso al panel, a los CSV y a los respaldos.

## Límites de detección

La información es declarada o inferida; puede ser aproximada, omitida o falsificada. Safari y navegadores con protección de privacidad pueden no facilitar marca o modelo. Algunos identifican el equipo como iPhone sin indicar la generación. Windows 10 y 11 comparten el User-Agent: sin Client Hints adecuados se registra expresamente «10 / 11 (no distinguible)». La detección de iPad con identificación de escritorio se marca como estimada. No se inventan versiones reales a partir de valores genéricos de Android.

La solicitud opcional de Client Hints espera como máximo 500 ms y no realiza llamadas a un proveedor. Si la API falta, falla o se demora, el envío continúa con los datos disponibles. El backend valida tipos, límites y campos permitidos; no almacena el User-Agent completo. No se capturan IMEI, MAC, número de serie, ubicación ni huellas de canvas.

Estos metadatos **no prueban identidad y no se usan para bloquear duplicados**: equipos distintos pueden compartirlos. Se mantienen los controles persistidos por invitación, cookie, identificador local y número declarado, con IP como señal y límite de frecuencia. Un reintento del mismo envío devuelve el comprobante y conserva los metadatos originales aunque cambie el tamaño de la ventana.

## Migración y verificación

La revisión Alembic `9a7e3c2d1f60` agrega cinco columnas opcionales y cuatro índices. Los registros anteriores mantienen valores nulos y aparecen como «Sin registro (respuesta anterior)», con columnas técnicas vacías en CSV. No se atribuyen dispositivos retrospectivamente.

Aplicar las migraciones antes de iniciar la versión nueva, como indica `backend/instructions.txt`. La imagen local ejecuta la migración mediante `RUN_MIGRATIONS=true`. En un despliegue con varias réplicas ejecutar una sola vez como tarea de release antes de actualizar los procesos.

Las pruebas cubren detección y límites, datos faltantes, idempotencia, persistencia, filtros, porcentajes con registros anteriores, protección administrativa, escape HTML/CSV y migraciones con conservación de opiniones. `scripts/verify-device-migration.py` verifica upgrade/downgrade/upgrade usando el conector nativo en una base temporal de MariaDB local. No ejecuta downgrade contra la base de la encuesta.

Referencias técnicas: [Client Hints del navegador](https://developer.mozilla.org/en-US/docs/Web/API/NavigatorUAData/getHighEntropyValues), [detección de Windows mediante Client Hints](https://learn.microsoft.com/en-us/microsoft-edge/web-platform/how-to-detect-win11) y [parser de User-Agent](https://uap-python.readthedocs.io/latest/quickstart.html).
