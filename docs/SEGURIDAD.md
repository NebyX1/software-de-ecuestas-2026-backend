# Controles de participación y seguridad

## Qué se puede garantizar

La base de datos impide registrar dos respuestas para la misma invitación o para un identificador de participación sujeto a unicidad. El servidor verifica los datos y el estado; modificar JavaScript o el almacenamiento del navegador no elimina las restricciones persistidas. La garantía depende de mantener la base, las claves HMAC y el identificador de encuesta estables.

No existe una garantía de «una persona, una respuesta» para un formulario público sin identidad verificada. Una persona puede borrar datos del navegador, cambiar de dispositivo y declarar otro número. El celular tiene validación de formato y unicidad, **sin comprobación de titularidad**. La URL base de un anuncio puede compartirse; lo que se restringe es la invitación emitida para responder.

## Capas

| Riesgo | Control | Límite práctico |
| --- | --- | --- |
| Compartir el enlace individual | Token aleatorio ligado a cookie HttpOnly y UUID local; validación del servidor | El propio navegador autorizado sigue pudiendo abrir su invitación |
| Reusar un enlace enviado | Consumo transaccional; estado utilizado; recuperación idempotente del mismo envío | Un comprobante idempotente no representa otra respuesta |
| Doble clic, dos pestañas o solicitudes simultáneas | Bloqueo de invitación y restricciones únicas en MariaDB, misma transacción que la respuesta | Los errores de infraestructura deben mostrarse y permitir un reintento seguro |
| Repetir desde el mismo navegador | Cookie del servidor y UUID persistido, ambos con huellas HMAC en servidor | Borrar datos, usar otro navegador o modo privado debilita el reconocimiento |
| Repetir con otro navegador | Unicidad del número declarado y, según política opcional, de IP | El número declarado puede ser ajeno o inventado; no acredita identidad |
| Automatización | Verificador local Redis de un solo uso, campo trampa, tiempo mínimo y límites distribuidos; Turnstile opcional | Una suma puede automatizarse; estas barreras no constituyen prueba de humanidad infalible |
| Obtener claves de acceso administrativo | Argon2, verificador numérico, OTP por correo con caducidad, intentos y consumo único | La seguridad del correo administrador también es necesaria |
| Peticiones desde otros sitios | Cookie SameSite, CSRF y orígenes exactos | Solo confiar en los proxies realmente presentes |
| Filtración en CSV | Exportación autenticada, identificadores excluidos, escape de fórmulas | Los comentarios pueden contener datos personales escritos voluntariamente |

## IP y proxies

La política elegida por el responsable es **IP como señal y límite de frecuencia**, con bloqueos por navegador y número declarado. `SURVEY_ENFORCE_IP_UNIQUENESS=false` viene seleccionado. Hogares, oficinas, instituciones y operadoras pueden compartir direcciones; no se los excluye permanentemente después de una respuesta.

Los límites Redis por IP se pueden ajustar mediante `SURVEY_LINK_IP_LIMIT` y `SURVEY_CHALLENGE_IP_LIMIT`. El verificador tiene caducidad, intentos y consumo único ligado al navegador y la invitación. La unicidad estricta por IP queda disponible como opción explícita y tiene pruebas propias; no es la configuración elegida.

`TRUSTED_PROXY_COUNT` debe corresponder a la cadena real hasta Flask. Con Nginx del frontend y sin que Coolify añada otra IP a la cadena de aplicación, se confía en el salto de Nginx. Revisar los encabezados en el despliegue real. El contenedor del backend no debe aceptar tráfico directo de Internet que permita falsificar encabezados de proxy. No asignar un número alto «para que funcione».

IPv6 con direcciones temporales, NAT de operadoras, VPN, proxys y redes móviles limitan la utilidad de la IP. El filtrado por país o reputación, si se agrega en el perímetro, es una señal adicional y no una prueba de identidad o residencia.

## Datos y secretos

Cada respuesta incluye información técnica descriptiva: dispositivo, sistema operativo, navegador, aplicación de acceso y, cuando están disponibles, modelo, idioma, zona horaria y dimensiones de pantalla. Se informa en el formulario y se muestra únicamente en el panel autenticado y sus exportaciones. Puede ser aproximada o falsificada; no se usa como prueba de identidad ni como restricción adicional de unicidad. No se guarda el User-Agent completo ni se capturan identificadores de hardware. Ver [registro de dispositivos](DISPOSITIVOS.md).

Teléfonos, tokens, identificadores e IP no se guardan en texto claro como parte de las opiniones. Se usan HMAC con una clave independiente de la clave de sesiones. No rotar `IDENTITY_HMAC_KEY` ni cambiar `SURVEY_ID` durante el relevamiento sin un plan de migración: invalidaría comparaciones con las huellas históricas.

Las tablas de control no tienen relación directa con las respuestas. Esto reduce vinculación, pero no constituye anonimato matemático: horarios, contenido libre y acceso privilegiado a infraestructura pueden permitir correlaciones. Limitar acceso, registrar exportaciones y no capturar cuerpos de API en logs, trazas o herramientas de errores.

No instalar el píxel de Meta ni enviar respuestas, teléfono o preferencias políticas como eventos de conversión. No enviar datos de encuesta a servicios publicitarios. Los UTM son texto no confiable y no autorizan acceso.

La encuesta informa participación voluntaria, confidencialidad y uso estadístico, incluyendo preguntas electorales y opción de no responder. Antes del lanzamiento, el responsable debe completar sus datos de contacto, plazos de conservación y canal para solicitudes en la política de privacidad. La preparación técnica no acredita cumplimiento normativo por sí sola.

## Operación

- Servir con HTTPS; usar cookies seguras en producción y dominios exactos.
- Redis es obligatorio para límites compartidos; una caída debe impedir operaciones sujetas a controles y no abrir un camino sin límites.
- SMTP debe enviar realmente el OTP administrativo. Probar el verificador local y, si se habilita, Turnstile con el dominio definitivo antes de lanzar anuncios.
- Programar respaldo de MariaDB y las claves en un gestor seguro, probar restauración y conservar las restricciones únicas. Un backup de opiniones sin las tablas de control permite repetir participación tras restaurar.
- Conservar la unicidad hasta cerrar el relevamiento. Eliminar metadatos expirados mediante el comando de mantenimiento documentado y definir la conservación de respuestas con el responsable.
- Revisar tasas de rechazo por IP, fallos del verificador, OTP administrativo, errores, disponibilidad, latencia y cambios en dependencias. Probar iOS y Android dentro de Facebook e Instagram y fuera de ellos.

La protección del backend depende también de la configuración de red, logs y backups de Coolify. El reporte de verificación distingue pruebas automatizadas y de contenedores de los pasos que requieren la cuenta real de producción.

La auditoría de dependencias incluye la biblioteca C del conector de MariaDB. Consultar `backend/SECURITY_AUDIT.md`: existe un único aviso asignado por el auditor al paquete Python cuyo componente C ya está corregido en la imagen y cuya versión se valida en build y al iniciar en producción. No se presenta como una auditoría bruta sin alertas.
