"""
Los reportes y la corrida: fecha del reporte, carpeta del dia, un reporte por vez con su resultado.
Cada reporte es una funcion (page, fecha, carpeta) -> Path del archivo descargado.
"""
import shutil
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.sync_api import Page

import config
from traxion import BotError, Sesion, guardar_debug, log


@dataclass
class Resultado:
    nombre: str
    archivo: Path | None = None
    error: str | None = None


class NoProgramado(BotError):
    """El reporte todavia no esta programado (falta inspeccionar su pantalla)."""


def fecha_del_reporte(ahora: datetime | None = None) -> date:
    """
    La fecha se fija UNA vez, al arrancar. El cron corre a las 23:59: si la corrida pasa la
    medianoche, la fecha sigue siendo la del dia en que arranco. Si el bot arranca de madrugada
    (antes de HORA_CORTE_FECHA, por ejemplo porque el cron se demoro), es el reporte de ayer.
    """
    ahora = ahora or datetime.now()
    if ahora.hour < config.HORA_CORTE_FECHA:
        return ahora.date() - timedelta(days=1)
    return ahora.date()


def es_hoy(fecha: date) -> bool:
    """Si es False, la corrida paso la medianoche: no sirven los filtros "Hoy"/"Del dia", hay que pedir la fecha."""
    return fecha == date.today()


def carpeta_del_dia(fecha: date) -> Path:
    carpeta = config.REPORTES_DIR / fecha.isoformat()
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def limpiar_reportes(hoy: date | None = None) -> None:
    """Borra las carpetas reportes/AAAA-MM-DD con mas de REPORTES_RETENCION_DIAS (tienen datos personales)."""
    if not config.REPORTES_DIR.exists():
        return
    limite = (hoy or date.today()) - timedelta(days=config.REPORTES_RETENCION_DIAS)
    for carpeta in config.REPORTES_DIR.iterdir():
        try:
            if carpeta.is_dir() and date.fromisoformat(carpeta.name) < limite:
                shutil.rmtree(carpeta)
                log(f"Reportes viejos borrados: {carpeta.name}")
        except (ValueError, OSError):
            pass  # carpeta con otro nombre o bloqueada: no se toca


# --- Reportes (se programan despues de inspeccionar el HTML real de cada pantalla) ---

def depositos(page: Page, fecha: date, carpeta: Path) -> Path:
    raise NoProgramado("todavia no esta programado (falta inspeccionar FINANCIERO > Depositos)")


def cuentas(page: Page, fecha: date, carpeta: Path) -> Path:
    raise NoProgramado("todavia no esta programado (falta inspeccionar GESTORES > Cuentas)")


def ventas(page: Page, fecha: date, carpeta: Path) -> Path:
    raise NoProgramado("todavia no esta programado (falta inspeccionar REPORTES > Ventas)")


REPORTES = [("Depósitos", depositos), ("Cuentas", cuentas), ("Ventas", ventas)]


def motivo_de(e: Exception) -> str:
    texto = str(e).strip()
    return texto.splitlines()[0] if texto else type(e).__name__


def ejecutar(sesion: Sesion, fecha: date, carpeta: Path, reportes=None) -> list[Resultado]:
    """
    Corre los reportes de a uno. Si uno falla, se anota el motivo y se sigue con el resto.
    Despues de un error la pagina puede quedar en cualquier estado: se cierra sesion y se vuelve a
    entrar. Si no se puede volver a entrar, los que faltan quedan con ese motivo.
    """
    resultados: list[Resultado] = []
    pendientes = list(reportes if reportes is not None else REPORTES)
    while pendientes:
        nombre, funcion = pendientes.pop(0)
        log(f"--- {nombre} ---")
        try:
            archivo = funcion(sesion.page, fecha, carpeta)
            resultados.append(Resultado(nombre, archivo=archivo))
            log(f"{nombre}: OK ({archivo.name})")
            continue
        except Exception as e:  # noqa: BLE001 - un reporte que falla no puede frenar a los demas
            motivo = motivo_de(e)
            resultados.append(Resultado(nombre, error=motivo))
            log(f"{nombre}: ERROR {motivo}")
            if isinstance(e, NoProgramado):
                continue
            if not isinstance(e, BotError):
                log(traceback.format_exc())
            if sesion.page is not None:
                guardar_debug(sesion.page, f"{nombre}_error")
        if pendientes:
            try:
                log("Se vuelve a iniciar sesion para seguir con el resto")
                sesion.iniciar()
            except Exception as e:  # noqa: BLE001
                motivo = f"no se pudo volver a iniciar sesion ({motivo_de(e)})"
                log(f"ERROR: {motivo}")
                resultados += [Resultado(n, error=motivo) for n, _ in pendientes]
                break
    return resultados
