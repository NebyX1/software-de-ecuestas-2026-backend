# Prueba de recepción, gráficas y descarga CSV

Verificación del 22 de octubre de 2026, America/Montevideo. Ejecutada con servicios reales locales: frontend Nginx, backend Gunicorn con conector MariaDB nativo, MariaDB 11.4, Redis, SMTP Mailpit y HTTPS con certificado temporal.

## Muestra registrada

Se enviaron **52 respuestas mediante la API pública**, dos por cada uno de los 26 recorridos residenciales. Cada envío obtuvo cookie, token CSRF, invitación y verificador propios, y terminó con confirmación persistida del servidor. No se insertaron opiniones directamente por SQL. El estado posterior de cada invitación confirmó su consumo.

La muestra incluye los seis municipios, Minas y localidades de pertenencia negativa o desconocida; votos y partidos condicionados; distintas evaluaciones de las 18 áreas; selecciones múltiples y excluyentes; ocho perfiles HTTP de dispositivo/navegador, incluyendo Facebook, Instagram y falta de User-Agent; y comentarios con comas, comillas, saltos de línea, tildes y emoji. También se incluyen fórmulas y HTML como texto para comprobar neutralización y escape.

Los perfiles técnicos son simulados: esta prueba no representa una prueba física de Safari, Facebook o Instagram. El flujo de navegador se ejecuta en Chromium.

Para comprobar fechas, **únicamente se ajustó `created_at` de esas 52 filas de prueba**, dentro del relevamiento reservado `local-verification-*`. Las fechas se distribuyen a ambos lados de las 03:00 UTC, medianoche de Uruguay en esas fechas. No se alteraron opiniones, controles de participación ni datos de otros relevamientos.

## Resultados contrastados

Las **34 gráficas del cuestionario y cuatro de dispositivos** se compararon contra los envíos, categoría por categoría: cantidades, denominadores, porcentajes, ancho de barras y etiquetas. Se comprobó también la serie diaria y el total seleccionado. La muestra tiene **36 respuestas con evaluación municipal**, seis por municipio; **Minas tiene dos respuestas sin evaluación municipal**. El partido utiliza solo el denominador de quienes contestaron que votaron. Las selecciones múltiples conservan sus porcentajes por persona y pueden sumar más de 100%.

Se descargaron los CSV **desde el botón del panel en el navegador**, guardando el archivo recibido y analizándolo con el lector estándar `csv` de Python. No se validó únicamente que una URL devolviera `200`.

| Selección | Respuestas, filas CSV y filas del listado filtrado |
| --- | ---: |
| Todas | 52 |
| Minas | 2 |
| Municipio de Mariscala | 6 |
| Otra zona rural + Mariscala | 2 |
| Sistema operativo Android | 19 |
| Votó Sí + Frente Amplio | 2 |
| Día 20/10/2026 en Uruguay | 13 |
| Fecha sin resultados | 0; archivo con encabezados válidos |

Cada descarga contiene **57 columnas**, sin duplicados, y exactamente los registros seleccionados. Se verificaron ID único, fecha UTC, versión de aviso, todas las respuestas y los datos técnicos; orden cronológico estable; UTF-8 con BOM; comas, comillas y saltos de línea; escape de fórmulas; y ausencia de teléfono, UUID local, token, IP o sus HMAC. El nombre del archivo y la finalización efectiva de la descarga también se verificaron.

El listado completo se recorrió en tres páginas de **25 + 25 + 2 filas**, sin repetir ni omitir IDs. Los siete listados filtrados coinciden con los IDs de sus respectivos CSV. Las ocho descargas generaron ocho eventos de auditoría. Antes del login y después del logout, la exportación exige autenticación. El login utilizó contraseña, número verificador y código recibido por SMTP local. El comentario con HTML se presentó como texto y no ejecutó JavaScript. No se registraron excepciones de JavaScript.

## Exportación superior al lote de 250

Se registraron otras **261 respuestas por las rutas públicas** en relevamientos temporales `integration-*` y se exportaron desde una sesión de administrador común con doble factor. El mismo escenario se ejecutó con PyMySQL en la suite y con **`mariadbconnector` dentro de la imagen real del backend**.

En ambos casos el CSV contiene **261 filas únicas y 57 columnas**, conserva exactamente comentarios multilínea y selecciones, y no pierde registros al superar el lote interno de 250. Se comprobaron gráficas, acceso protegido, auditoría y revocación al cerrar sesión. Los registros y el administrador temporal se eliminaron al finalizar; los otros relevamientos permanecieron intactos.

## Reproducir y revisar

Preparar el entorno de HTTPS local según README, con `.env.e2e` y el prefijo de límites reservado. Ejecutar desde la raíz:

```powershell
node tests/e2e/prepare.mjs
$env:E2E_BASE_URL='https://localhost:8443'
$env:E2E_ALLOW_SELF_SIGNED='1'
npm run test:analytics
python scripts/test-native-csv.py
```

La prueba analítica es una suite independiente de los 34 recorridos generales: `prepare.mjs` debe ejecutarse antes de cada suite para iniciar su muestra desde cero. GitHub Actions contiene ambas ejecuciones en ese orden, además de la comprobación nativa de 261 filas.

Archivos locales de evidencia, excluidos de Git y de los paquetes de despliegue:

- `artifacts/analitica-todas.csv`: descarga real de las 52 respuestas ficticias.
- `artifacts/analitica-*.csv`: las otras selecciones exportadas.
- `artifacts/analitica-verificacion.json`: conteos y comprobaciones por selección.
- `artifacts/csv-native-verification.json`: resultado con el conector nativo y 261 respuestas.
- `artifacts/analitica-dashboard.png`, `analitica-seleccion-multiple.png` y `analitica-dispositivos.png`: capturas del panel poblado.

Estas pruebas acreditan el entorno descrito; los dominios, SMTP público, red y configuración definitiva de Coolify requieren su comprobación al desplegar. Los resultados generales están en [VERIFICACION.md](VERIFICACION.md).
