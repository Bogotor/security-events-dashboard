# Validación de la primera versión

Fecha: 15 de noviembre de 2026.

## Comprobaciones automáticas

Entorno: Python 3.9.6. Comando: `python3 -m unittest discover -s tests -v`.

Resultado: **19 pruebas aprobadas**. Incluyen detecciones, ventana de cinco minutos, separación entre cuentas, reinicio después del acceso exitoso, eventos tardíos, duplicados, rollback transaccional, persistencia al reabrir SQLite, notas y controles de acceso HTTP.

También se ejecutó el ejemplo de API contra un servidor temporal: siete eventos generan las tres reglas esperadas y su salida no muestra la credencial de prueba.

La sintaxis del JavaScript se comprobó con `node --check static/app.js`. Node solo se usó para esta verificación; no es un requisito para ejecutar la aplicación.

## Comprobaciones en navegador

- Panel vacío: contadores en cero e instrucciones para comenzar.
- Escenario sospechoso: seis eventos y dos alertas, una de prioridad alta.
- Detalle: seis eventos visibles como evidencia del acceso después de fallos.
- Investigación: resolución con nota guardada, cambio de contadores y conservación después de recargar.
- Cambio de permisos: un evento y una alerta adicional.
- Actividad habitual: dos eventos adicionales, sin nuevas alertas.
- Filtros combinados: búsqueda de usuario y tipo de evento devuelven el cambio de permisos esperado.
- Fecha sin coincidencias: estado vacío y contador cero, sin modificar los totales globales.
- Paginación: nueve eventos distribuidos en dos páginas.
- Vista móvil: distribución en una columna y dos columnas de métricas; ancho del documento de 375 px sin desbordamiento horizontal global observado. La tabla dispone de desplazamiento propio.

Captura: [panel.jpg](panel.jpg), con datos sintéticos creados durante las pruebas.

## Límites de esta validación

No se ha validado un despliegue público, carga de producción, accesibilidad exhaustiva ni recuperación desde copias de respaldo. La exportación JSON se verificó mediante la API; la descarga desde el botón no se probó de extremo a extremo. Los controles de esta versión sirven para un laboratorio local y no sustituyen la preparación de una demo pública.


## Preparación de la demo WSGI

Se amplió la suite a **39 pruebas**: las 19 originales y 20 adicionales para aislamiento entre visitantes, cookies, origen y CSRF, persistencia entre instancias, cuotas, expiración, reinicio, restauración de SQLite y configuración de la entrada WSGI.

En la previsualización local WSGI se verificaron en navegador: rótulo de demo, escenario sospechoso con seis eventos y dos alertas, investigación guardada en SQLite, descarga JSON y reinicio a cero eventos. Captura: [demo-wsgi.jpg](demo-wsgi.jpg).

Estos resultados locales no sustituyen las comprobaciones pendientes en Alwaysdata: HTTPS, variables del sitio, comportamiento del servidor del proveedor, almacenamiento persistente y consumo de recursos. La suite de integración continua se ejecuta también en Python 3.9, 3.12 y 3.14.
