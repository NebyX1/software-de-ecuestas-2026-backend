# Rendimiento de la entrada — 2026-11-01

## Cambio

La entrada anterior completaba cuatro llamadas API consecutivas antes de mostrar el formulario: configuración/CSRF, creación del enlace, otra consulta CSRF y validación de sesión. También requería la negociación CORS de los POST. No había una espera artificial, pero esas idas y vueltas se acumulaban.

La entrada nueva necesita dos llamadas API: `/api/csrf?entry=survey` prepara la cookie durante la configuración ya necesaria; `/api/survey/links` confirma que el navegador devolvió una cookie válida y entrega el token con el estado de sesión activa. El frontend utiliza esa confirmación del servidor en memoria y muestra la encuesta al cambiar al enlace. El HTML incluye una conexión anticipada al origen de la API, calculada a partir de la misma `VITE_API_URL`.

No se agregan variables de entorno ni pausas. La transición sigue en blanco. El tiempo total depende de la red, la descarga inicial y el dispositivo; reducir llamadas no representa una garantía de tiempo cero.

## Controles y compatibilidad

- El estado de sesión solo se incluye si el POST recibió una cookie firmada válida previamente establecida. Si el servidor tuvo que emitir o corregir la cookie, el cliente conserva la validación separada.
- Las recargas y los enlaces abiertos directamente vuelven a consultar al servidor. La confirmación rápida no se persiste en el borrador ni en almacenamiento local.
- La configuración de CSRF usada por administración y simulación, sin `entry=survey`, no crea una cookie de participación.
- Crear invitaciones, impedir duplicados, validar Turnstile cuando esté configurado y consumir respuestas conservan sus controles del servidor. No se modificó el esquema ni se añadieron migraciones.
- Cada parte funciona durante un despliegue escalonado: el frontend anterior ignora el campo opcional y el frontend nuevo utiliza el flujo anterior cuando el backend todavía no lo entrega.

## Validación

Las pruebas del navegador comprueban dos llamadas en la entrada nueva y cuatro en el flujo compatible, un solo POST de creación bajo StrictMode, pantalla vacía durante las solicitudes pendientes, consentimiento explícito y nueva validación tras recargar. Los casos de cookies rechazadas y respuestas malformadas fallan sin mostrar el formulario.

Se aprobaron 134 pruebas del frontend y 11 pruebas de Chromium sobre la compilación final, además de lint y compilación. La suite del backend aprobó 1.747 casos, con 7 casos optativos de MariaDB omitidos en esa corrida; esos 7 casos se aprobaron aparte contra MariaDB real. Una comprobación posterior de arranque/correo aprobó 31 casos, incluyendo la conservación del comando `check-mail`.

Se validaron también 9 casos integrados HTTP y 5 por HTTPS con frontend y API separados: las dos entradas rápidas, la compatibilidad con la respuesta anterior, recargas, enlace inexistente, enlace copiado, envío, simulación/CSV y administración. La simulación se comprobó aisladamente después de terminar las otras pruebas que escriben en MariaDB.

Las comprobaciones de simulación deben ejecutarse sin otras pruebas que modifiquen simultáneamente los contadores globales de la misma base de datos; la simulación no escribe respuestas. Las credenciales, archivos CSV y artefactos de pruebas permanecen excluidos de Git.
