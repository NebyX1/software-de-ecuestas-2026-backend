# IP asociada a cada respuesta

Cada respuesta nueva conserva en `survey_responses.ip_address` la dirección IPv4/IPv6 completa, normalizada por el servidor, de la conexión que efectivamente envía el formulario. Se toma de `request.remote_addr` después de ProxyFix; no se acepta desde JSON ni desde encabezados leídos directamente por el servicio.

La dirección aparece en el listado y detalle administrativos y en la columna `ip_address` del CSV autenticado. No se devuelve en las respuestas de la API pública. Los reintentos conservan la dirección del primer envío confirmado. Almacenar la IP no activa unicidad estricta: varias personas de una red compartida pueden responder según la política vigente.

## Migración y despliegue

La revisión `c41d8a92b730`, posterior a `9a7e3c2d1f60`, añade únicamente una columna nullable. Conserva las opiniones existentes; sus IP anteriores quedan en NULL y se muestran como «Sin registro (respuesta anterior)». No existe un backfill fiable desde las huellas de control separadas de las opiniones.

Aplicar las migraciones con el mecanismo ya configurado de release o el entrypoint con `RUN_MIGRATIONS=true` antes de admitir tráfico con el modelo nuevo. Respaldar la base antes de la actualización. No ejecutar downgrade en producción para probarlo: eliminaría la nueva columna y sus valores.

Desplegar primero el backend. La API acepta el nuevo aviso `2026-03` y conserva las versiones `2026-01`/`2026-02` durante la actualización. Después publicar el frontend, cuyo aviso informa el registro de IP junto a las respuestas. El frontend mantiene únicamente `VITE_API_URL`.

`TRUSTED_PROXY_COUNT=1` corresponde al único proxy HTTPS de Coolify delante del backend. Mantener Gunicorn accesible públicamente solo mediante ese proxy. NAT, VPN y redes compartidas pueden hacer que varias personas tengan una misma IP; la dirección registrada no es un identificador físico único del equipo.

La simulación continúa sin guardar respuestas ni IP de respuesta. Su CSV conserva las mismas columnas con `ip_address` vacía.
