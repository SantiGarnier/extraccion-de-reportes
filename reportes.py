"""
Los reportes y la corrida: fecha del reporte, carpeta del dia, un reporte por vez con su resultado.
Cada reporte es una funcion (page, fecha, carpeta) -> (archivo descargado, cantidad de registros).
"""
import shutil
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.sync_api import Page

import config
from traxion import (BotError, Sesion, abrir_pestania, buscar, exportar_excel, guardar_debug, ir_a, log,
                     marcar_botones, poner_valor)


@dataclass
class Resultado:
    nombre: str
    archivo: Path | None = None
    error: str | None = None
    registros: int | None = None


def fecha_del_reporte(ahora: datetime | None = None) -> date:
    """
    La fecha se fija UNA vez, al arrancar. El cron corre pasada la medianoche: si el bot arranca
    antes de HORA_CORTE_FECHA es el reporte del dia anterior completo (asi entra lo de las 23:59).
    Despues de esa hora (una corrida a mano durante el dia) es el de hoy.
    """
    ahora = ahora or datetime.now()
    if ahora.hour < config.HORA_CORTE_FECHA:
        return ahora.date() - timedelta(days=1)
    return ahora.date()


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


# --- Reportes ---
# Depositos y Ventas usan la pestania "Por Filtros" con la fecha del reporte de 00:00:00 a 23:59:59
# (y no "Hoy"): la corrida de la madrugada pide el dia anterior, y con --fecha se puede repetir cualquiera.

def _filtrar_por_fecha(page: Page, fecha: date) -> None:
    dia = f"{fecha:%d/%m/%Y}"
    poner_valor(page, "Desde fecha", dia)
    poner_valor(page, "Desde hora", "00:00:00", aceptables=("0:00:00",))
    poner_valor(page, "Hasta fecha", dia)
    poner_valor(page, "Hasta hora", "23:59:59")


def depositos(page: Page, fecha: date, carpeta: Path) -> tuple[Path, int]:
    ir_a(page, "FINANCIERO", "Depositos", "Administracion de Depositos")
    abrir_pestania(page, "Por Filtros", "Desde fecha")
    _filtrar_por_fecha(page, fecha)
    marcar_botones(page, "Incluir", ["PEI", "T.Credito", "Rec.Terceros", "Efectivo", "Depositos", "Cheques"])
    marcar_botones(page, "Depositos", ["Enviados", "Recibidos"])
    registros = buscar(page, "Depositos")
    archivo = exportar_excel(page, carpeta / f"Depositos_{fecha.isoformat()}", "Depositos",
                             columnas=["Fecha", "Nro.Ope.", "Cuenta", "Importe", "Estado"],
                             timeout=config.TIMEOUT_BUSQUEDA_LARGA_MS)
    return archivo, registros


def cuentas(page: Page, fecha: date, carpeta: Path) -> tuple[Path, int]:
    # Los saldos son los del momento de la consulta: no hay "saldo de ayer"
    ir_a(page, "GESTORES", "Cuentas", "Cuentas")
    abrir_pestania(page, "General", "Mostrar")
    marcar_botones(page, "Mostrar", ["Cta.Cte.", "Saldo Disponible", "Saldo Virtual"])
    # con los saldos marcados la busqueda es lenta (~40 s en produccion)
    registros = buscar(page, "Cuentas", timeout=config.TIMEOUT_BUSQUEDA_LARGA_MS)
    archivo = exportar_excel(page, carpeta / f"Cuentas_{fecha.isoformat()}", "Cuentas",
                             columnas=["Numero", "Nombre", "Cta.Cte.", "Saldo Disponible", "Saldo Virtual"],
                             timeout=config.TIMEOUT_BUSQUEDA_LARGA_MS)
    return archivo, registros


def ventas(page: Page, fecha: date, carpeta: Path) -> tuple[Path, int]:
    ir_a(page, "REPORTES", "Ventas", "Consulta de Ventas")
    abrir_pestania(page, "Por Filtros", "Desde fecha")
    _filtrar_por_fecha(page, fecha)
    registros = buscar(page, "Ventas", timeout=config.TIMEOUT_BUSQUEDA_LARGA_MS)
    archivo = exportar_excel(page, carpeta / f"Ventas_{fecha.isoformat()}", "Ventas",
                             columnas=["Nro.Ope.", "Fecha", "Producto", "Estado", "Importe"],
                             timeout=config.TIMEOUT_BUSQUEDA_LARGA_MS)
    return archivo, registros


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
            archivo, registros = funcion(sesion.page, fecha, carpeta)
            resultados.append(Resultado(nombre, archivo=archivo, registros=registros))
            log(f"{nombre}: OK ({archivo.name}, {registros} registros)")
            continue
        except Exception as e:  # noqa: BLE001 - un reporte que falla no puede frenar a los demas
            motivo = motivo_de(e)
            resultados.append(Resultado(nombre, error=motivo))
            log(f"{nombre}: ERROR {motivo}")
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
