# Despliegue de Vigía en Alwaysdata Free

Estado: entrada WSGI preparada. La cuenta, el subdominio y el despliegue remoto todavía deben verificarse en el proveedor. Este documento no afirma que la demo ya esté publicada.

## Qué se publica

```text
Navegador -> HTTPS de Alwaysdata -> Python WSGI (wsgi.py)
                                     |
                                     +-> reglas existentes de app.py
                                     +-> SQLite privado por sesión
```

Las simulaciones y las detecciones se ejecutan en Python. El navegador solo muestra los resultados y envía acciones a la API. No hay un motor de detección alternativo en JavaScript.

La entrada local `python3 app.py` sigue disponible con sus datos y credencial de ingesta independientes. La pública utiliza `wsgi.py` y `webapp.py`; no se debe exponer el servidor HTTP de desarrollo a internet.

## Cuenta y plan

1. Crear la cuenta personal y seleccionar explícitamente **Free (0 €)**. Evitar el plan Plus de prueba.
2. Confirmar el correo electrónico y activar autenticación en dos pasos desde el panel personal.
3. Elegir el nombre de cuenta y comprobar el subdominio asignado por el proveedor.

La contraseña, el segundo factor y la aceptación de condiciones los gestiona el propietario de la cuenta. No guardar credenciales en el chat ni en GitHub.

Condiciones consultadas el 15 de noviembre de 2026: uso personal no comercial, 1 GB de disco compartido, 256 MB de RAM, 1/4 CPU, subdominio alwaysdata.net y tres días de copias. Durante el primer año se requiere entrar al panel de administración al menos cada 120 días. Verificar estas condiciones al registrar la cuenta.

## Instalar el código

En los ejemplos siguientes, sustituir `CUENTA` por el nombre confirmado del alojamiento. Los comandos del proveedor usan `python`, tal como indica su documentación.

Desde una sesión SSH de Alwaysdata:

```sh
mkdir -p "$HOME/apps"
git clone https://github.com/Bogotor/security-events-dashboard.git "$HOME/apps/vigia"
mkdir -p "$HOME/vigia-data"
chmod 700 "$HOME/vigia-data"
```

No hay paquetes externos que instalar. Seleccionar Python **3.12** para el sitio.

## Configurar el sitio

En **Web > Sites**, añadir o editar el sitio:

| Campo | Valor |
| --- | --- |
| Tipo | Python WSGI |
| Dirección | El subdominio asignado, por ejemplo `CUENTA.alwaysdata.net` |
| Ruta de aplicación | `/home/CUENTA/apps/vigia/wsgi.py` |
| Directorio de trabajo | `/home/CUENTA/apps/vigia` |
| Versión de Python | 3.12 |

Variables de entorno del sitio:

```text
VIGIA_PUBLIC_ORIGIN=https://CUENTA.alwaysdata.net
VIGIA_DATA_DIR=/home/CUENTA/vigia-data
```

El origen no lleva barra final ni ruta. La carpeta de datos es privada, persistente y separada del repositorio. La aplicación no necesita la credencial local `ingest.token`: la ingesta externa está deshabilitada en la demo pública.

Comprobar el certificado y activar la redirección HTTP -> HTTPS desde Alwaysdata. Reiniciar el sitio después de configurar sus variables. No definir una ruta estática que exponga el directorio del repositorio ni la carpeta de datos. La aplicación sirve únicamente los tres archivos de interfaz permitidos.

## Verificar antes de compartir

1. Abrir `/health` por HTTPS y comprobar `status: ok`.
2. Abrir el panel y comprobar el rótulo **DEMO** y la explicación **Python y SQLite, funcionando en el servidor**.
3. Ejecutar el escenario sospechoso: seis eventos y dos alertas.
4. Guardar una nota y marcar una alerta como resuelta. Recargar y comprobar persistencia.
5. Abrir el sitio en una ventana privada: sus datos deben estar vacíos.
6. Reiniciar el sitio desde Alwaysdata y comprobar que la sesión original conserva los datos.
7. Probar exportación y reinicio; comprobar que la otra sesión no se modifica.
8. Confirmar que `/api/events`, `/wsgi.py` y `/data/registry.sqlite3` no permiten acceso.

## Sesiones, almacenamiento y límites

- Cookie de sesión opaca: `Secure`, `HttpOnly`, `SameSite=Lax`, prefijo `__Host-` y duración de 24 horas.
- Se almacena en SQLite un registro de sesiones y una base privada para cada una. No se usan identificadores introducidos por el visitante para crear rutas.
- La caducidad bloquea el acceso a partir de 24 horas. Los archivos de sesiones caducadas se eliminan cuando comienza una sesión nueva; no hay un servicio de fondo ni una eliminación programada exacta al cumplirse el plazo.
- Hasta 128 sesiones activas, 384 eventos por sesión, 120 lecturas por minuto y 20 intentos de modificación por minuto por sesión. Se admiten hasta 10 sesiones nuevas por minuto en total.
- Los contadores usan ventanas de minuto fijas y persisten en SQLite. La creación masiva de sesiones puede agotar temporalmente la capacidad; estos controles no sustituyen protección contra ataques volumétricos.
- Cada visitante puede reiniciar solo su sesión. El reinicio borra eventos, alertas y notas; no reinicia sus cuotas por minuto.
- La demo permite únicamente los escenarios ficticios incluidos. No es una plataforma para recibir registros de sistemas reales. No ingresar datos personales ni credenciales en las notas.
- El registro central serializa las operaciones entre procesos WSGI. Esto prioriza consistencia y facilidad de revisión sobre concurrencia elevada.

## Copia consistente de SQLite

Las copias de archivos del proveedor no garantizan por sí solas una instantánea consistente de SQLite. Para crear una copia con su API de respaldo:

```sh
cd "$HOME/apps/vigia"
python scripts/backup_demo.py --data-dir "$HOME/vigia-data" --output-dir "$HOME/vigia-backups"
```

La herramienta pausa brevemente las operaciones de la demo usando el registro de SQLite, crea instantáneas y verifica su integridad. No depende de un proceso siempre encendido. El destino debe estar fuera de los datos activos. Las copias conservan identificadores de sesión y notas, por lo que deben permanecer privadas y no subirse a GitHub.

Para restaurar, detener el sitio, conservar la carpeta activa como respaldo, copiar el contenido completo de la instantánea elegida a una nueva carpeta privada y cambiar `VIGIA_DATA_DIR` a esa carpeta. Reiniciar y comprobar eventos y notas. Las sesiones conservan su fecha original de caducidad; restaurar no las prolonga. La prueba automatizada verifica restauración con una aplicación independiente; el procedimiento remoto debe comprobarse en Alwaysdata.

## Actualizar el código

Con las pruebas de GitHub aprobadas, actualizar desde SSH con `git pull --ff-only` dentro del repositorio y reiniciar el sitio. Los datos están fuera del código y permanecen intactos. No hay despliegue automático configurado todavía.

## Referencias

- [Python y WSGI en Alwaysdata](https://help.alwaysdata.com/en/docs/web-hosting/languages/python/configuration/).
- [Oferta y límites](https://help.alwaysdata.com/en/docs/admin-billing/billing/public-cloud-prices/).
- [Inactividad](https://help.alwaysdata.com/en/docs/admin-billing/profile/suspension/).
- [Copias de respaldo](https://help.alwaysdata.com/en/docs/web-hosting/backups/).
