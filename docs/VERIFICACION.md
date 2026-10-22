# Verificación ejecutada

Última revisión: 22 de octubre de 2026, America/Montevideo. Entorno local: Windows, Docker, MariaDB 11.4, Redis 7.4, backend Gunicorn/Python 3.11 y frontend Nginx. Pruebas Python adicionales con entorno 3.12.13. Estos resultados acreditan el entorno descrito, no una ausencia absoluta de defectos ni un despliegue en Coolify ya realizado.

| Verificación | Resultado |
| --- | --- |
| Backend completo con MariaDB y Redis disponibles | **1.637 aprobadas**, sin omitidas ni fallos |
| Frontend: pruebas Vitest | **104 aprobadas** |
| TypeScript estricto, ESLint y build Vite | Aprobados |
| Recorridos Chromium por HTTPS local con servicios en contenedores | **35 aprobados**: 34 generales y una simulación analítica independiente |
| Paridad real Marshmallow/Zod | **1.446 casos** coincidentes; pasos municipales y siete transiciones del store aprobados |
| Conservación del cuestionario | **116 opciones/áreas, 14 preguntas literales y cuatro límites** contrastados con la versión original |
| Concurrencia real MariaDB | Cinco pruebas: mismo envío, teléfono, dispositivo, IP estricta y dos personas distintas en conexión compartida |
| Continuidad y municipios sobre MariaDB real | Sexta prueba de integración: 26 ramas, persistencia y denominadores por municipio; Minas excluida del bloque municipal |
| Exportación superior al lote interno | Séptima prueba de integración: 261 envíos, 261 filas únicas y 57 columnas; repetida con el conector nativo de la imagen |
| Recepción → gráficas → descarga | 52 respuestas, 38 gráficas contrastadas por selección, ocho CSV descargados desde el navegador y listados coincidentes |
| Migraciones con conector nativo | Upgrade → downgrade → upgrade aprobado; ocho tablas InnoDB incluyendo revisión Alembic |
| Respaldo y restauración | Ocho tablas restauradas en base temporal; todos los conteos coinciden; base temporal eliminada |
| Dockerfiles independientes y health checks | Imágenes construidas y servicios saludables |
| Modo producción de Coolify | Un escenario HTTPS completo con cookies seguras, CSRF estricto, CORS, SMTP STARTTLS verificado, 38 gráficas y CSV |
| Redespliegue independiente | Backend reemplazado con IP nueva; Nginx conservó su contenedor y recuperó la API sin reinicio |
| Configuración de frontend y backend en dos dominios | **24 pruebas de despliegue aprobadas**, con tres nuevas para CSRF por host, sesiones separadas y CORS exacto |
| npm audit | Cero vulnerabilidades informadas, incluidas dependencias de desarrollo |
| Auditoría Python completa | Sin avisos adicionales pendientes; un aviso de Connector/C justificado mediante versión nativa corregida y control obligatorio, ver abajo |

Las 1.446 pruebas de contrato, 35 de metadatos, 26 de API residencial, 21 de configuración/CORS de despliegue y siete de integración están incluidas en las 1.637 del backend; no se suman otra vez. Las de integración son cinco carreras, una de persistencia de las 26 ramas y una de exportación de 261 respuestas. Cuando no se configura `TEST_DATABASE_URL`, esas siete se omiten expresamente. En la ejecución final sí se configuró, junto con Redis real, y se aprobaron las siete. Las advertencias restantes de pytest corresponden a interfaces deprecadas de utilidades de prueba; el build Vite informa comentarios de anotaciones de dependencias que Rollup elimina. No hubo fallos de compilación ni excepciones de JavaScript en los recorridos.

La verificación adicional del modo `production` y los archivos privados de importación de variables para Coolify se documentan en [PRUEBA_COOLIFY.md](PRUEBA_COOLIFY.md). El responsable definió `https://uypolls.online` para el frontend y `https://mapi.uypolls.online` para el backend; ambos están incluidos en los hosts permitidos y CORS conserva el origen del frontend. Los recursos internos siguen pendientes y los campos de correo quedan vacíos. No se realizó un despliegue en el servidor definitivo.

La simulación analítica adicional registra 52 respuestas por API pública y contrasta las 38 gráficas, sus denominadores y porcentajes, las fechas de Uruguay, ocho descargas reales con 57 columnas, los listados filtrados y las tres páginas de 25 + 25 + 2 registros. Se comprobaron acentos, emoji, comillas, saltos de línea, neutralización de fórmulas, escape HTML, acceso y auditoría. La exportación de 261 respuestas se ejecutó además dentro de la imagen del backend con `mariadbconnector`, conservando todas las filas al cruzar el lote de 250. Metodología y resultados por filtro en [PRUEBA_ANALITICA.md](PRUEBA_ANALITICA.md).

La auditoría de continuidad abarca los seis municipios y las 26 ramas residenciales, **Minas sin pertenencia ni evaluación municipal**, cambios al retroceder, restauración de borradores, partido y texto Otro condicionados, selecciones excluyentes y las dos partes de áreas. Documenta las correcciones y la diferencia entre pruebas de interfaz y de persistencia en [LOGICA_ENCUESTA.md](LOGICA_ENCUESTA.md).

La ampliación de registro técnico incluye cinco pruebas nuevas de captura en frontend y 35 en backend: detección Windows/Android/iOS/iPad, Meta, datos faltantes o malformados, límites, persistencia, idempotencia, filtros, CSV y escape HTML/fórmulas, permisos y migración SQLite. Se verificó además upgrade/downgrade/upgrade nativo en una base MariaDB temporal, conservando una opinión y su proyección. Los recorridos HTTPS verifican el envío de metadatos, cuatro gráficos técnicos, filtros y columnas CSV, además del detalle administrativo. Ver [DISPOSITIVOS.md](DISPOSITIVOS.md).

## Alcance de los recorridos reales en navegador

1. Completar el cuestionario mediante la interfaz, verificar que edad no venga seleccionada, responder las 18 áreas, resolver el verificador local, copiar la invitación a otro navegador y comprobar rechazo, simular una caída de conexión al enviar, conservar borrador y reintentar, confirmar guardado persistido, recargar y comprobar enlace utilizado.
2. Revisar la presentación a 390 px, comprobar ausencia de desbordamiento horizontal y terminar correctamente por el filtro de menor de edad.
3. Acceder al panel con contraseña y suma, comprobar que aún esté protegido antes del código, recibir un correo por SMTP en Mailpit, verificar el código, abrir dashboard poblado con 34 variables y cuatro gráficos técnicos, comprobar filtros y CSV de dispositivo, abrir detalle con metadatos, revisar panel móvil y cerrar sesión.
4. Recorrer las 26 ramas residenciales hasta el contacto, con las preguntas del municipio correcto o sin bloque cuando no corresponde; comprobar requisitos de partido, evaluaciones, ambas partes de áreas y prioridades.
5. Retroceder y confirmar localidad sin cambios, cambiar Mariscala por Zapicán y exigir opiniones nuevas, cambiar a Minas y omitir municipios, y cambiar pertenencia rural a no pertenencia.
6. Restaurar un borrador adelantado, terminar por no residencia y recargar, y cambiar condiciones de partido y texto Otro eliminando respuestas ocultas.
7. Mantener activo el límite de CSV: diez descargas permitidas y la undécima rechazada con `429`. La preparación solo limpia los contadores del prefijo E2E reservado.
8. Ejecutar por separado la muestra de 52 respuestas, contrastar cada gráfica y descargar ocho CSV mediante el botón del panel, con comparación íntegra de filas y columnas, listado paginado y acceso revocado después del logout.

Capturas locales en `artifacts/`: inicio de encuesta en escritorio/móvil y dashboard en escritorio/móvil. Se inspeccionaron visualmente. El directorio también contiene reportes y credenciales **solo locales de pruebas**, y está excluido de Git y de las exportaciones.

El SMTP de este recorrido es un servidor real local de pruebas, no un correo enviado al proveedor público. La participación no usa proveedor de mensajería: el número declarado se comprueba por formato y unicidad, sin verificar titularidad. El verificador numérico usa Redis real en el recorrido y las pruebas de concurrencia; se probaron caducidad, intentos, vinculación, consumo único, campo trampa, tiempo mínimo y recuperación después de un fallo de base. Turnstile es opcional y tiene pruebas de hostname/acción y fallos con transportes simulados.

Se probó HTTPS mediante un proxy TLS local y certificado temporal, con la misma normalización de IP/protocolo y Host prevista para Coolify. El navegador completó los POST de encuesta y administración. Una petición con token CSRF válido y Referer de otro origen fue rechazada con 400, lo que también acredita que Flask recibía el protocolo HTTPS. Se corrigieron tanto el encabezado como la etiqueta HTML de Referrer-Policy: `same-origin` permite el control SSL estricto de Flask-WTF y no envía la referencia a terceros. Esto no sustituye el certificado ni la configuración de red del dominio definitivo.

## Auditoría nativa

`pip-audit` informa `PYSEC-2026-217` sobre el paquete Python `mariadb==1.1.14`. El [aviso original de MariaDB](https://github.com/MariaDB/server/security/advisories/GHSA-pv9p-5w55-55jm) corresponde a **Connector/C**, corregido en **3.3.19 y 3.4.9**. Se comprobó **3.4.9** dentro de la imagen final. El Docker build y el inicio en modo producción rechazan bibliotecas sin la corrección.

Solo ese ID tiene una excepción documentada en CI; no se describe el informe bruto como «cero alertas». Ver `backend/SECURITY_AUDIT.md`. Las otras cinco vulnerabilidades inicialmente detectadas en cuatro paquetes se corrigieron mediante actualizaciones y se volvieron a auditar. El contenedor usa el conector nativo y MariaDB real, no solo el sustituto de pruebas PyMySQL.

## Reproducción

Desde la carpeta raíz, con dependencias y servicios locales preparados según README:

```sh
npm run check
node scripts/check-contract.mjs
backend/.venv/Scripts/python.exe scripts/test-database-integration.py
python scripts/verify-backup.py
node tests/e2e/prepare.mjs
npm test --prefix tests/e2e
```

`prepare.mjs` requiere el conjunto iniciado con `.env.e2e`, `SURVEY_ID=local-verification-*` y `RATELIMIT_KEY_PREFIX=local-verification-e2e`; no puede preparar ni limpiar producción. Solo elimina contadores de ese prefijo reservado, sin vaciar Redis ni desactivar límites. En Linux el intérprete del entorno se encuentra en `backend/.venv/bin/python`.

Los workflows incluidos se revisaron y sus comandos principales se ejecutaron localmente. No se han ejecutado GitHub Actions remotos porque este trabajo no publicó cambios ni creó repositorios remotos nuevos.

## Pendiente antes de admitir respuestas públicas

- Crear/configurar los dos repositorios de destino y los recursos de Coolify; publicar `uypolls.online` y `mapi.uypolls.online` con HTTPS, verificar su DNS y completar la red interna.
- Configurar IP/CIDR del proxy y comprobar IP real desde dos conexiones distintas, cookies seguras y CSRF por HTTPS en el dominio definitivo. El flujo HTTPS ya se probó localmente; la topología real de Coolify sigue pendiente. Se reconsulta DNS del backend para admitir despliegues independientes.
- Configurar SMTP público y comprobar entrega real del código, SPF/DKIM y capacidad del remitente.
- Si se decide activar Turnstile opcional, crear su widget y probar claves públicas/privadas, dominio y acción. No es un requisito para la operación autónoma del verificador local.
- Probar Facebook e Instagram en dispositivos físicos iOS y Android. La emulación móvil de Chromium no verifica los navegadores internos de esas aplicaciones.
- Completar datos de contacto y conservación de la política de privacidad, configurar backups externos y probar una restauración desde ellos.

La preferencia del responsable quedó aplicada: IP como señal y límite de frecuencia; controles por dispositivo, número declarado y enlace, con verificador local y sin proveedor de mensajería. La unicidad estricta por IP se conserva como opción, desactivada por defecto.
