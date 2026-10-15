"""
Bot de extraccion de reportes de Traxion (Depositos, Cuentas, Ventas) y envio por mail.

Uso:
    python main.py                      saca los reportes y los manda por mail
    python main.py --fecha 2026-10-14   idem, para otra fecha (por ejemplo, para repetir un dia)
    python main.py --sin-mail           saca los reportes pero no manda el mail
    python main.py --solo-login         entra, guarda una captura en debug/ y cierra sesion
    python main.py --probar-mail        manda un mail de prueba con un adjunto chico (no entra a Traxion)

Sale con 0 si todo salio bien, y con 1 si fallo algun reporte, el login o el mail.
"""
import argparse
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

import config
import correo
import reportes
from reportes import Resultado
from traxion import Sesion, guardar_debug, limpiar_debug, log


def correr(fecha: date, solo_login: bool) -> list[Resultado]:
    """Entra, corre los reportes y cierra sesion (siempre). Devuelve un resultado por reporte."""
    limpiar_debug()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.HEADLESS, slow_mo=0 if config.HEADLESS else 150)
        context = browser.new_context(viewport={"width": 1600, "height": 1000}, locale="es-AR",
                                      accept_downloads=True)
        context.set_default_timeout(config.TIMEOUT_MS)
        sesion = Sesion(context)
        try:
            try:
                sesion.iniciar()
            except Exception as e:  # noqa: BLE001 - sin login igual se manda el mail con el motivo
                log(f"ERROR en login: {e}")
                if sesion.page is not None:
                    guardar_debug(sesion.page, "login_error")
                motivo = f"no se pudo iniciar sesion en Traxion ({reportes.motivo_de(e)})"
                if solo_login:
                    return [Resultado("Login", error=motivo)]
                return [Resultado(nombre, error=motivo) for nombre, _ in reportes.REPORTES]

            if solo_login:
                guardar_debug(sesion.page, "solo_login")
                return [Resultado("Login")]

            return reportes.ejecutar(sesion, fecha, reportes.carpeta_del_dia(fecha))
        finally:
            sesion.terminar()  # cierra la sesion en Traxion: no queda viva al terminar
            context.close()
            browser.close()


def probar_mail(fecha: date) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        ejemplo = Path(tmp) / f"{fecha.isoformat()}_prueba.csv"
        ejemplo.write_text("columna;valor\nprueba;1\n", encoding="utf-8")
        resultados = [Resultado("Prueba", archivo=ejemplo),
                      Resultado("Ejemplo de reporte fallido", error="esto es un error de ejemplo")]
        ahora = datetime.now()
        msg = correo.armar(fecha, resultados, ahora, ahora)
        msg.replace_header("Subject", f"[PRUEBA] {msg['Subject']}")
        return mandar(msg)


def mandar(msg) -> bool:
    try:
        correo.enviar(msg)
        return True
    except Exception as e:  # noqa: BLE001
        log(f"ERROR enviando el mail: {reportes.motivo_de(e)}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Extraccion de reportes de Traxion")
    parser.add_argument("--fecha", type=date.fromisoformat,
                        help="fecha del reporte AAAA-MM-DD (por defecto, la del dia en que arranca)")
    parser.add_argument("--sin-mail", action="store_true", help="no manda el mail")
    parser.add_argument("--solo-login", action="store_true",
                        help="entra, guarda una captura en debug/ y cierra sesion")
    parser.add_argument("--probar-mail", action="store_true",
                        help="manda un mail de prueba con un adjunto chico (no entra a Traxion)")
    args = parser.parse_args()

    inicio = datetime.now()
    fecha = args.fecha or reportes.fecha_del_reporte(inicio)

    if args.probar_mail:
        log("=== Prueba de mail ===")
        return 0 if probar_mail(fecha) else 1

    modo = "solo login" if args.solo_login else f"reportes del {fecha:%d/%m/%Y}"
    log(f"=== Inicio ({modo}, headless={config.HEADLESS}) ===")
    reportes.limpiar_reportes()
    resultados = correr(fecha, args.solo_login)
    todo_ok = all(r.error is None for r in resultados)

    if not args.solo_login and not args.sin_mail:
        todo_ok = mandar(correo.armar(fecha, resultados, inicio, datetime.now())) and todo_ok

    fallidos = [r.nombre for r in resultados if r.error]
    log(f"=== Fin {'OK' if todo_ok else 'con ERROR'}" + (f" (fallaron: {', '.join(fallidos)})" if fallidos else "")
        + " ===")
    return 0 if todo_ok else 1


if __name__ == "__main__":
    sys.exit(main())
