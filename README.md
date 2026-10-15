# extraccion-de-reportes

Bot que entra a Traxion con el usuario operador, exporta a Excel los reportes de **Depósitos**,
**Cuentas** y **Ventas**, y los manda por mail. Siempre cierra la sesión en Traxion, aunque algo falle.

> Estado: los tres reportes están programados contra el HTML real de testing y probados contra un
> Traxion de mentira. Falta la primera corrida completa contra testing.

## Los reportes

| Reporte | Pantalla | Qué hace el bot | Archivo |
|---|---|---|---|
| Depósitos | FINANCIERO → Depositos | Pestaña "Por Filtros" con la fecha del reporte (00:00:00 a 23:59:59), marca todo "Incluir" y "Depositos: Enviados / Recibidos", Buscar, Exportar a Excel | `Depositos_AAAA-MM-DD.csv` |
| Cuentas | GESTORES → Cuentas | Pestaña "General", en "Mostrar" marca Cta.Cte., Saldo Disponible y Saldo Virtual, Buscar, Exportar a Excel | `Cuentas_AAAA-MM-DD.csv` |
| Ventas | REPORTES → Ventas | Pestaña "Por Filtros" con la fecha del reporte (resto de filtros por defecto: Estado "Confirmada"), Buscar, Exportar a Excel | `Ventas_AAAA-MM-DD.csv` |

- "Exportar a Excel" baja en realidad un **CSV** (separado por `;`, coma decimal, ISO-8859-1). Se manda tal cual,
  después de verificar que no esté vacío, que no sea una página HTML y que tenga las columnas esperadas.
- Un día sin movimientos **no es un error**: el archivo sale con el encabezado y el mail dice "sin movimientos".
- Los saldos de Cuentas son los del **momento de la consulta** (no hay "saldo de ayer").
- En "Funciones" hay acciones peligrosas (Suspender, Activar, Confirmar y Anular marcados, etc.): el bot solo
  clickea el texto exacto "Exportar a Excel".

## Instalación

```powershell
pip install -r requirements.txt
python -m playwright install chromium        # en Linux: python -m playwright install --with-deps chromium
copy .env.example .env                       # y completar (el .env no se sube a git)
```

## Uso

```powershell
python main.py                      # saca los reportes y los manda por mail
python main.py --fecha 2026-10-14   # idem, para otra fecha (para repetir un día)
python main.py --sin-mail           # saca los reportes pero no manda el mail
python main.py --solo-login         # entra, guarda una captura en debug/ y cierra sesión
python main.py --probar-mail        # manda un mail de prueba con un adjunto chico (no entra a Traxion)
```

Sale con código **0** si todo salió bien y **1** si falló algún reporte, el login o el mail.

### Qué pasa en cada corrida

1. Se fija la **fecha del reporte** (ver abajo) y se borran las carpetas de reportes viejas.
2. Login. Los reportes corren de a uno y cada archivo va a `reportes/AAAA-MM-DD/`.
3. Si un reporte falla, se anota el motivo, se cierra sesión, se vuelve a entrar y se sigue con el resto.
4. Logout, siempre.
5. Se manda **un mail** con los reportes que salieron como adjuntos y, para los que fallaron, el motivo.
   Si falló alguno, el asunto termina en "- CON ERRORES". Si no se pudo entrar a Traxion, el mail
   igual sale, con el motivo.

### Fecha del reporte (corrida de las 23:59)

La fecha se fija **una sola vez, al arrancar**:

- Si el bot arranca a las 23:59 del 15/10 y termina pasada la medianoche, sigue sacando los reportes del **15/10**.
  Depósitos y Ventas no usan las pestañas "Hoy": piden siempre la fecha del reporte en "Por Filtros".
- Si arranca de madrugada (antes de `HORA_CORTE_FECHA`, por defecto las 6:00), por ejemplo porque el cron se
  demoró, saca los del **día anterior**.
- Con `--fecha AAAA-MM-DD` se fuerza una fecha.

Los archivos quedan en `reportes/AAAA-MM-DD/` y se borran a los `REPORTES_RETENCION_DIAS` (por defecto 30).

## Mail

Todo sale del `.env`: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`, `SMTP_SECURE` y
`MAIL_ASUNTO`. `SMTP_TO` acepta varios destinatarios separados por coma.

- `SMTP_SECURE=false` usa el puerto 587 con STARTTLS obligatorio; `true` usa SSL directo (465).
- En testing se usa **Ethereal** (`smtp.ethereal.email`): acepta los mails pero **no los entrega**.
  Se ven en la web de Ethereal, en "Messages". Para que lleguen de verdad a las casillas hace falta el SMTP real.

## Cron (servidor Linux)

Ejemplo para correr todos los días a las 23:59:

```cron
59 23 * * * cd /opt/extraccion-de-reportes && flock -n /tmp/extraccion-de-reportes.lock ./venv/bin/python main.py >> logs/cron.log 2>&1
```

- **El servidor tiene que estar en hora argentina** (`timedatectl set-timezone America/Argentina/Buenos_Aires`):
  la fecha del reporte y el horario del cron salen del reloj local.
- `flock -n` evita que se pisen dos corridas (por ejemplo, una manual y la del cron).
- `logs/cron.log` junta lo que no pase por el log del bot (por ejemplo, un error de Python al arrancar).
- `HEADLESS=true` en el `.env` del servidor.

## Diagnóstico

- **Log del día:** `logs/bot_AAAAMMDD.log`. Los parámetros de sesión de Traxion (`_s`, `_k`) salen tapados.
- **Capturas:** `debug/`, ante un error (y con `--solo-login`). El HTML se guarda solo con `DEBUG_HTML=true`.
  Se borran solas a los `DEBUG_RETENCION_DIAS` días porque pueden tener datos personales.
- `debug/`, `logs/` y `reportes/` están en `.gitignore`: nunca se commitean.

## Pruebas

Corren con Chromium headless contra un Traxion de mentira (`tests/fake_traxion.py`), sin red. El mail se
prueba sin mandar nada:

```powershell
python -m unittest -v
```

## Archivos

| Archivo | Qué hace |
|---|---|
| `config.py` | Lee el `.env` |
| `traxion.py` | Errores, log, debug, espera del ajaxifier (`click_y_esperar`), login y logout |
| `reportes.py` | Fecha del reporte, carpeta del día, los reportes y la corrida de a uno |
| `correo.py` | Arma y manda el mail |
| `main.py` | Arma el navegador y corre todo (logout garantizado en un `finally`) |
| `tests/` | Traxion de mentira y pruebas |
