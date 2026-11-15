# Vigía · Panel de eventos de seguridad

Proyecto de portafolio para recibir eventos de una aplicación de prueba, detectar comportamientos sospechosos y documentar su investigación.

![Panel local con eventos y alertas de ejemplo](docs/panel.jpg)


## Stack

| Parte | Tecnología | Responsabilidad |
| --- | --- | --- |
| Servidor y API | Python 3.9+, biblioteca estándar | Validación, recepción de eventos e investigaciones |
| Almacenamiento | SQLite | Persistencia local de eventos, alertas y notas |
| Interfaz | HTML, CSS y JavaScript sin frameworks | Panel adaptable, filtros, simulaciones y evidencia |
| Detección | Reglas temporales en Python | Secuencias de fallos, accesos posteriores y cambios de permisos |
| Pruebas | unittest | Detecciones, transacciones, persistencia y controles HTTP |
| Integración continua | GitHub Actions | Pruebas en Python 3.9, 3.12 y 3.14, y revisión de sintaxis JavaScript |

**Estado:** laboratorio local funcional. La demo pública todavía no está desplegada. Las alertas requieren investigación y no confirman por sí solas una intrusión.

## Ejecutar en tu computador

Requisito: Python 3.9 o superior. No requiere pip, Node, Docker, cuenta en la nube ni una API de IA.

Desde esta carpeta:

```sh
python3 app.py
```

Abrir http://127.0.0.1:8765 en el navegador. Para detener el servidor, presionar `Ctrl+C` en su terminal. Si el puerto está ocupado, ejecutar `python3 app.py --port 8766` y usar esa dirección.

Los eventos y las investigaciones se conservan en `data/events.sqlite3`. El archivo `data/ingest.token` contiene una credencial de ingesta local. Toda la carpeta `data/` está excluida de Git y no debe publicarse. No se precargan eventos: las simulaciones crean los datos de ejemplo cuando las ejecutas.

## Probar el recorrido principal

1. Pulsar **Acceso sospechoso**. Aparecen seis eventos y dos alertas: intentos repetidos y acceso después de múltiples fallos.
2. Abrir la alerta de prioridad alta y revisar los seis eventos de evidencia.
3. Elegir **En investigación**, añadir una nota y guardar.
4. Abrir la misma alerta, completar la nota y marcar **Resuelta**. Aparecerá en la pestaña Resueltas.
5. Pulsar **Actividad habitual**. Agrega dos eventos sin crear alertas nuevas.
6. Pulsar **Cambio de permisos**. Agrega un evento y una alerta con los roles anterior y nuevo.
7. Probar búsqueda por usuario o IP, filtro de tipo, fecha local y paginación. Usar **Exportar datos** para descargar eventos, alertas y notas como JSON; no incluye la credencial de ingesta y no sustituye una copia restaurable de SQLite.

Cada simulación usa una cuenta ficticia diferente para evitar mezclar escenarios. Las métricas muestran todos los datos guardados; los filtros solo afectan la tabla de eventos. Las alertas tienen su propio filtro de estado. El panel consulta cambios cada 15 segundos, excepto mientras hay un diálogo abierto o se ejecuta una simulación.


## Enviar un evento a la API

Con el servidor iniciado, desde otra terminal en esta carpeta:

```sh
python3 examples/send_event.py
python3 examples/send_event.py --type login_success
python3 examples/send_event.py --type role_changed
```

El ejemplo envía un evento para `analista@demo.test` a `POST /api/events`. Genera un identificador único y una fecha UTC actual, y lee la credencial desde `data/ingest.token` sin mostrarla. Repetir cinco veces el primer comando dentro de cinco minutos y luego enviar un acceso exitoso permite observar las dos reglas de autenticación con la misma cuenta. El cambio de permisos utiliza los roles `viewer` y `admin`.

Si usas otro puerto, añade `--port 8766`. El parámetro `--user otra-cuenta@demo.test` permite separar escenarios. Envía únicamente datos ficticios.

Formato de un evento (la fecha y el identificador del script se generan al ejecutarlo):

```json
{
  "event_id": "evento-de-ejemplo-001",
  "occurred_at": "2026-11-15T12:00:00Z",
  "type": "login_failed",
  "user": "analista@demo.test",
  "source_ip": "192.0.2.25",
  "metadata": {}
}
```

Ver [contrato de la API y reglas](docs/ARQUITECTURA.md) para los campos admitidos y sus límites.

## Pruebas

```sh
python3 -m unittest discover -s tests -v
```

Las pruebas HTTP abren un puerto temporal en la interfaz local. Se verifican ventanas temporales, separación por cuenta, reinicio de secuencias al ingresar, recepción fuera de orden, idempotencia, transacciones, persistencia y controles HTTP.

## Objetivo

Demostrar el ciclo completo de una solución: definición del problema, implementación, pruebas de detección, despliegue y documentación de resultados y limitaciones.

## Primera versión

- Recibir eventos estructurados de accesos exitosos, accesos fallidos y cambios de permisos.
- Guardar eventos y alertas en una base de datos local.
- Mostrar un panel con filtros por usuario, tipo de evento y fecha.
- Detectar cinco accesos fallidos para una misma cuenta en cinco minutos.
- Detectar un acceso exitoso precedido por esos fallos dentro de la misma ventana.
- Alertar cuando cambia el rol de un usuario.
- Permitir marcar una alerta como pendiente, en investigación o resuelta, con una nota.
- Generar escenarios sintéticos reproducibles para demostrar cada regla.

Los umbrales iniciales son decisiones del proyecto, no valores universales. Se documentarán sus falsos positivos y limitaciones. Una alerta indica que se necesita revisión, no que se confirmó un ataque.

## Componentes implementados

1. Generador de eventos sintéticos.
2. API de recepción con validación de datos y credencial para la ingesta.
3. Almacenamiento SQLite para la primera versión local.
4. Motor de reglas basado en ventanas de tiempo.
5. Panel web de eventos, alertas y notas de investigación.

No requiere un modelo de IA ni una API de pago. Las detecciones iniciales serán reglas explícitas y verificables.

## Costos y publicación

El desarrollo y las pruebas iniciales se ejecutarán en el computador del autor con herramientas gratuitas. No se contratará infraestructura para esta etapa.

La publicación será una etapa posterior: se elegirá alojamiento considerando persistencia de datos, límites del plan gratuito, autenticación y costos vigentes. No se debe asumir que un disco local de un alojamiento gratuito conserva SQLite entre reinicios.

La demo pública utilizará datos sintéticos y separará la experiencia de demostración de cualquier futura ingesta de datos reales. Un dominio propio es opcional.

## Evidencias que debe incluir el portafolio

- Instrucciones reproducibles para ejecutar la aplicación.
- Diagrama de arquitectura y modelo de eventos.
- Pruebas de límites temporales, escenarios normales y eventos que generan alertas.
- Tratamiento de eventos duplicados y fuera de orden, o documentación explícita de esas limitaciones.
- Investigación de ejemplo: evento, detección, evidencia, posible falso positivo y resolución.
- Capturas y un video breve de la demo.
- Decisiones técnicas, riesgos conocidos y mejoras futuras.

## Manejo de datos

Usar identificadores y direcciones de ejemplo. No registrar contraseñas, tokens ni secretos. Mantener la recepción de eventos y las funciones de administración restringidas cuando se publique.

## Documentación

- [Arquitectura, API y límites](docs/ARQUITECTURA.md).
- [Investigación de ejemplo](docs/INVESTIGACION-EJEMPLO.md).
- [Resultados de validación](docs/VALIDACION.md).
- [Recordatorio: publicación y presentación a reclutadores](docs/CIERRE-PORTAFOLIO.md).

## Estado y siguiente etapa

Primera versión local implementada. Incluye API con ingesta autenticada, almacenamiento persistente, motor de reglas, panel, simulaciones, filtros, exportación e investigaciones.

Todavía no se ha publicado en internet. Esta versión escucha exclusivamente en el computador del autor y no autentica analistas locales. Antes de convertirla en una demo pública hay que preparar el alojamiento, el aislamiento entre visitantes y los controles descritos en la arquitectura.

Al cerrar el proyecto retomaremos la publicación de demo y repositorio, el video breve y los enlaces para CV y LinkedIn, según el recordatorio de cierre.


## Licencia

Por decisión del autor, esta versión se publica sin una licencia de reutilización.
