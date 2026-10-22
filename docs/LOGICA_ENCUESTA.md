# Auditoría de continuidad y preguntas condicionadas

Revisión del 22 de octubre de 2026. Se conservan las preguntas, opciones y límites del cuestionario original. Esta revisión comprueba coherencia entre respuestas, pantallas, validación del servidor y resultados; no verifica que la residencia declarada sea real.

## Reglas de residencia

**Minas no tiene bloque municipal en esta encuesta.** No se pregunta pertenencia municipal ni se solicita evaluar un municipio a quien selecciona Minas.

| Respuesta de residencia | Pregunta de pertenencia | Evaluación municipal |
| --- | --- | --- |
| Minas | No aparece | No aparece; el servidor rechaza datos municipales |
| Solís de Mataojo | No aparece; se determina por localidad | Las tres preguntas sobre Solís de Mataojo |
| José Pedro Varela | No aparece; se determina por localidad | Las tres preguntas sobre José Pedro Varela |
| Mariscala | No aparece; se determina por localidad | Las tres preguntas sobre Mariscala |
| Zapicán | No aparece; se determina por localidad | Las tres preguntas sobre Zapicán |
| José Batlle y Ordóñez | No aparece; se determina por localidad | Las tres preguntas sobre José Batlle y Ordóñez |
| Pirarajá | No aparece; se determina por localidad | Las tres preguntas sobre Pirarajá |
| Otra zona urbana o rural | Obligatoria, con los seis municipios y las opciones negativas/de desconocimiento originales | Solo si se selecciona uno de los seis; las preguntas nombran ese municipio |
| Otra zona: No pertenece a ninguno / No estoy seguro/a / Ns/Nc | Se conserva esa declaración | No aparece ni se permite enviar evaluación municipal |
| Localidad: Ns/Nc | No aparece | No se atribuye un municipio ni se exige evaluación |

Son **26 recorridos residenciales**: seis localidades municipales, Minas y localidad desconocida, más nueve opciones de pertenencia para cada una de las dos zonas «otra».

El backend determina el municipio de las seis localidades directas. Si un cliente envía explícitamente otro municipio, devuelve `422`; si envía el mismo, se acepta su representación canónica. Para «otra zona» la pertenencia se declara expresamente. Cuando corresponde evaluación municipal, las tres respuestas son obligatorias; cuando no corresponde, cualquiera de ellas es rechazada. En las respuestas de Minas no se guarda pertenencia municipal ni evaluación.

## Otras dependencias

| Condición | Comportamiento |
| --- | --- |
| Edad sin responder | No permite continuar a residencia |
| Menor de 18 años | Termina antes de preguntar residencia, localidad, opiniones o celular; no se inventa una respuesta de residencia |
| Residencia sin responder | No permite continuar a localidad |
| No reside en Lavalleja | Termina sin pedir opiniones ni celular |
| Votó: Sí | Exige partido; «Prefiero no responder / Ns/Nc» sigue siendo una respuesta válida |
| Votó: No / No recuerdo / Prefiero no responder | No muestra partido y elimina una elección anterior al cambiar de respuesta |
| Preocupaciones: Otro | Exige el texto «¿Cuál?»; si se deja de seleccionar Otro, elimina ese texto |
| Ninguno o Ns/Nc en preocupaciones | Excluyentes con las demás opciones y entre sí |
| Ns/Nc en prioridades | Excluyente con las demás prioridades |
| Preocupaciones y prioridades | Entre una y tres opciones, sin repeticiones; al alcanzar tres se deshabilitan opciones ordinarias no seleccionadas, conservando las elegidas. Las opciones excluyentes siguen disponibles |
| Evaluaciones por áreas | Exige las ocho de la primera parte y las diez de la segunda; cada parte valida por separado y permite Ns/Nc |
| Llegada al envío | Exige todas las respuestas aplicables, comentario y controles finales; el servidor vuelve a validar el conjunto |

## Retroceder, cambiar de respuesta y restaurar un borrador

- Cambiar localidad elimina la pertenencia anterior y las tres evaluaciones municipales. Si la nueva localidad tiene municipio, exige una evaluación nueva de ese municipio.
- Cambiar la pertenencia de una zona «otra» elimina las evaluaciones anteriores. Elegir no pertenencia o desconocimiento omite el bloque; elegir otro municipio exige respuestas nuevas.
- Confirmar la misma localidad o pertenencia conserva respuestas que siguen siendo aplicables.
- El paso guardado en el navegador no concede acceso a una pantalla: se comprueban los requisitos previos al navegar, al renderizar y al restaurar. Un borrador adelantado vuelve a la primera pregunta pendiente.
- La restauración elimina respuestas ocultas incompatibles y no confía en marcas de finalización ni comprobantes guardados en el borrador. La confirmación de envío procede del acuse del servidor.
- La segunda mitad de áreas tiene su propio formulario; no hereda el estado de envío ni mensajes de error de la primera.

## Cambios realizados durante la auditoría

1. Agregar control de requisitos en la navegación y en la restauración de borradores; antes podía mostrarse una pantalla posterior con requisitos pendientes.
2. Unificar frontend y backend para la representación explícita del municipio correcto y rechazar pertenencia municipal para Minas y localidad Ns/Nc.
3. Evitar que confirmar una localidad sin cambiarla borre sus respuestas municipales.
4. Eliminar la respuesta de residencia que se asignaba automáticamente al finalizar por edad.
5. Separar el estado de formulario de las dos mitades de áreas.
6. Evitar que elegir una cuarta opción reemplace silenciosamente una de las tres ya seleccionadas.

## Evidencia reproducible

- `backend/tests/test_contract_parity.py`: **1.446 casos**, incluidos 800 cruces de localidad/pertenencia/presencia de las tres preguntas municipales, escalas de cada municipio, campos y áreas faltantes y las ramas electorales y de selección. `node scripts/check-contract.mjs` ejecuta los mismos datos en Zod y Marshmallow y compara los resultados.
- `backend/tests/test_conditional_flow.py`: los **26 recorridos** mediante la API real de Flask; los intentos incompatibles devuelven `422`, no guardan respuestas ni consumen la verificación. El envío válido posterior usa el mismo desafío y guarda solo el municipio y preguntas aplicables.
- `backend/tests/test_database_integration.py`: además de las cinco carreras de concurrencia, recorre las 26 ramas en MariaDB y Redis reales. Comprueba la pertenencia guardada, columnas de CSV y denominadores: **18** respuestas municipales entre los 26 casos y **tres** por municipio al filtrar (localidad directa, otra zona urbana y otra rural). Minas y las opciones sin municipio quedan excluidas de esas evaluaciones.
- `frontend/src/utils/surveyFlow.test.ts`: requisitos previos, seis municipios, cambios de residencia/pertenencia, restauración, respuestas ocultas y finalización del borrador.
- `frontend/src/components/QuestionCheckbox.test.tsx`: exclusividad, máximo de tres y conservación de elecciones.
- `tests/e2e/conditional-flow.spec.ts`: las 26 ramas desde la entrada hasta el contacto en Chromium, más retrocesos, cambios de municipio, cambio a Minas, cambio a no pertenencia, partido/Otro, borrador adelantado y residencia no elegible. Los 26 recorridos de este archivo no envían la encuesta; su persistencia se prueba por la API sobre MariaDB y en el recorrido E2E de envío del archivo `survey.spec.ts`.

Los totales de toda la suite y los límites de la verificación están en [VERIFICACION.md](VERIFICACION.md). Las pruebas del navegador se ejecutan con HTTPS local, MariaDB, Redis y SMTP local; no sustituyen pruebas en los navegadores físicos de Facebook e Instagram.

La preparación E2E usa `RATELIMIT_KEY_PREFIX=local-verification-e2e` para aislar sus contadores Redis. Solo en `development`, con encuesta `local-verification-*` y ese prefijo exacto, `prepare.mjs` elimina contadores de esa prueba. No vacía Redis ni modifica los límites de la aplicación. El recorrido administrativo comprueba que la descarga número once siga siendo rechazada con `429` después de las diez permitidas por hora.
