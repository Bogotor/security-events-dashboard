# Ejemplo de investigación

## Escenario

Seleccionar «Acceso sospechoso». Se generan cinco fallos y un acceso exitoso para una cuenta ficticia única, desde una IP reservada para documentación. Las dos alertas son esperadas: intentos repetidos y acceso posterior a fallos.

## Hipótesis

Puede tratarse de una contraseña olvidada seguida de un acceso legítimo, o de un intento de adivinación que terminó con éxito. La regla no distingue entre ambos casos.

## Revisión

1. Abrir «Acceso después de múltiples fallos» y marcar «En investigación».
2. Revisar las horas, la cuenta y la IP en los seis eventos de evidencia.
3. En un caso real, consultar al propietario de la cuenta y contrastar con sesiones, dispositivos y otras fuentes. El laboratorio no dispone de esas fuentes: no inventar una confirmación.
4. Anotar: «Escenario sintético reproducido. Se verifican cinco fallos previos y un acceso exitoso dentro de cinco minutos. No hay evidencia adicional para confirmar compromiso. Detección validada para esta simulación».
5. Marcar «Resuelta»: se cierra la validación de la simulación, no una intrusión real.

## Comparación

Ejecutar «Actividad habitual». Un fallo seguido de un acceso exitoso no alcanza el umbral y no debe crear alertas nuevas.
