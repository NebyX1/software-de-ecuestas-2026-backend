# Auditoría de dependencias nativas

Las dependencias Python completas están fijadas en `requirements.lock`. La imagen compila el conector nativo contra la biblioteca del sistema y verifica su versión en build y al arrancar en producción.

## PYSEC-2026-217 / CVE-2026-44172

`pip-audit` asigna este aviso a `mariadb==1.1.14` de PyPI, sin versión Python corregida. El [aviso del fabricante](https://github.com/MariaDB/server/security/advisories/GHSA-pv9p-5w55-55jm) identifica como componente afectado **libmariadb / Connector/C**, versiones 3.3.1–3.3.18 y 3.4.1–3.4.8; las correcciones son **3.3.19 y 3.4.9**. Afecta al escape de parámetros con el juego Big5.

La imagen verificada el 21 de octubre de 2026 usa **Connector/C 3.4.9**, comprobado con `mariadb.client_version_info`. `app/utils/connector_security.py` impide compilar o arrancar en producción con una versión anterior a los umbrales corregidos. Esto acredita que la biblioteca nativa de esa imagen contiene la corrección; no significa que se ignoren todos los avisos de MariaDB ni otras vulnerabilidades.

La única excepción del comando de auditoría de CI es este ID concreto, por esa diferencia entre el paquete Python y la biblioteca enlazada. El Docker build ejecuta la comprobación nativa obligatoriamente. Cualquier otro aviso continúa haciendo fallar la auditoría:

```sh
python -m pip_audit --no-deps --disable-pip -r requirements.lock --ignore-vuln PYSEC-2026-217
docker build -t encuestas-backend:verified .
docker run --rm --entrypoint python encuestas-backend:verified -c "from app.utils.connector_security import verify_native_connector; print(verify_native_connector())"
```

No usar esta excepción al instalar una rueda enlazada con otra biblioteca sin ejecutar la comprobación. Si cambia el aviso del fabricante o el rango afectado, volver a revisar la excepción y el control de versión. El reporte bruto de la auditoría conserva el aviso; el reporte de verificación explica la evidencia de su resolución en la imagen.
