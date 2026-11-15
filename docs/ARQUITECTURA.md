# Arquitectura y decisiones de la versión local

## Flujo

```text
Generador de escenarios ─┐
                        ├─> API Python ─> validación ─> SQLite
Cliente con credencial ─┘                         │
                                                 v
                                      motor de reglas temporal
                                                 │
                                                 v
                                      alertas + investigaciones
                                                 │
                                                 v
                                      panel HTML / CSS / JS
```

Python 3.9+ y su biblioteca estándar evitan una instalación inicial de paquetes. SQLite conserva datos entre reinicios. La interfaz no necesita compilación ni recursos externos. Es una base educativa local; el servidor HTTP de la biblioteca estándar no es una plataforma de producción.

## Modelo de eventos

Cada evento contiene `event_id`, `occurred_at` (ISO 8601 con zona horaria), `type`, `user`, `source_ip` y `metadata`. Los únicos tipos son `login_failed`, `login_success` y `role_changed`. En un cambio de permisos, metadata requiere `old_role` y `new_role`, diferentes entre sí. No se aceptan campos adicionales ni metadatos arbitrarios.

El contenido de los campos de texto sigue siendo responsabilidad del emisor: la lista de campos permitidos no puede detectar un secreto pegado dentro de un nombre o una nota. Usar exclusivamente datos ficticios en el laboratorio.

## Reglas

1. **Intentos repetidos:** cinco o más fallos de una cuenta dentro de cinco minutos, con ambos extremos incluidos. Tras generar la alerta, se suprimen nuevas alertas de esta regla para esa cuenta durante cinco minutos. Un acceso exitoso reinicia la secuencia y la supresión.
2. **Acceso posterior a fallos:** un acceso exitoso con al menos cinco fallos previos dentro de esa misma ventana. Cada éxito vacía la secuencia de fallos de la cuenta.
3. **Cambio de permisos:** todo cambio entre dos roles diferentes merece revisión, aunque puede ser legítimo.

Las reglas agrupan por el identificador exacto de la cuenta, no por IP. No detectan ataques distribuidos entre muchas cuentas ni permiten inferir una intrusión confirmada. Una persona que olvida su contraseña puede generar un falso positivo.

## Duplicados, orden y persistencia

- Un `event_id` repetido con idéntico contenido normalizado no se inserta otra vez. Si cambia su contenido, se rechaza la operación.
- Los eventos se ordenan por su fecha en UTC. Los empates se resuelven por `event_id`; en esta versión no existe una secuencia externa para desambiguarlos.
- Cada ingesta recalcula todas las reglas dentro de una transacción. Así, los eventos que llegan tarde también participan en las detecciones.
- Un evento tardío puede cambiar las alertas y su evidencia. La identidad de una alerta es `regla:evento_que_la_dispara`. Si esa identidad se mantiene, se conservan sus notas y estado. Si desaparece, su investigación se conserva en la tabla interna, pero deja de mostrarse. No existe todavía historial de revisiones de una alerta.
- La versión local admite hasta 5000 eventos. Recalcular toda la historia facilita la revisión del algoritmo, pero no es la estrategia adecuada para un volumen de producción.
- SQLite serializa las escrituras mediante un bloqueo de la aplicación. Eventos, detecciones y cambios de investigación se guardan en disco; reiniciar el servidor no los borra.

## API local

| Método y ruta | Uso | Control |
| --- | --- | --- |
| GET `/api/state` | Eventos y alertas | Solo interfaz local y Host permitido |
| GET `/api/bootstrap` | Credencial temporal del panel | Solo interfaz local; sin CORS |
| GET `/api/export` | Exportación JSON | Solo interfaz local; no contiene la credencial de ingesta |
| POST `/api/events` | Recibir un evento | `Authorization: Bearer <credencial local>` |
| POST `/api/simulate` | Crear escenario | Origen exacto y `X-Panel-Token` |
| POST `/api/alerts/update` | Guardar estado y nota | Origen exacto y `X-Panel-Token` |

Los POST requieren JSON de hasta 16 KiB. Las notas admiten hasta 2000 caracteres. El servidor se enlaza exclusivamente a `127.0.0.1`. Verifica Host para reducir ataques de DNS rebinding y rechaza mutaciones del navegador con origen diferente. Usa consultas parametrizadas y escapa los valores antes de mostrarlos en HTML.

La credencial temporal del panel limita solicitudes desde otros orígenes; no es autenticación de un analista. Cualquier proceso local con acceso al servidor puede leer el panel y obtener esa credencial. Las notas y la base no están cifradas en disco.

## Antes de publicar

Faltan autenticación, autorización por usuario, HTTPS gestionado por el alojamiento, limitación de solicitudes, aislamiento entre visitantes y una estrategia de retención, respaldo y restauración. No exponer este servidor a internet mediante un túnel. Preparar un despliegue separado y revisar su modelo de amenazas.
