"""Configuracion del bot. Todo sale del archivo .env (nunca hardcodear credenciales)."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool(nombre: str, default: bool) -> bool:
    valor = os.getenv(nombre)
    if valor is None:
        return default
    return valor.strip().lower() in ("1", "true", "si", "sí", "yes")


def _ruta(nombre: str, default: str) -> Path:
    ruta = Path(os.getenv(nombre) or default)
    return ruta if ruta.is_absolute() else BASE_DIR / ruta


TRAXION_URL = os.getenv("TRAXION_URL", "https://testing.telerecargas.com.ar/")
TRAXION_USER = os.getenv("TRAXION_USER", "")
TRAXION_PASS = os.getenv("TRAXION_PASS", "")

# Fechas y horas del bot (fecha del reporte, log, mail, saldos de Cuentas) en hora de Buenos Aires,
# aunque el servidor este en UTC
ZONA_HORARIA = ZoneInfo(os.getenv("ZONA_HORARIA", "America/Argentina/Buenos_Aires"))

HEADLESS = _bool("HEADLESS", False)
# Tope de seguridad: el bot avanza apenas ocurre el evento esperado; esto solo corta si el
# servidor no responde NUNCA (no es un tiempo de espera fijo)
TIMEOUT_MS = int(os.getenv("TIMEOUT_MS", "60000"))
# "Buscar" de Cuentas con saldos tarda ~40 s: tope de seguridad para las busquedas largas
TIMEOUT_BUSQUEDA_LARGA_MS = int(os.getenv("TIMEOUT_BUSQUEDA_LARGA_MS", "180000"))

# Los reportes tienen datos financieros y personales: carpeta en .gitignore. Una subcarpeta por dia.
REPORTES_DIR = _ruta("REPORTES_DIR", "reportes")
REPORTES_RETENCION_DIAS = int(os.getenv("REPORTES_RETENCION_DIAS", "30"))
# El cron corre pasada la medianoche y saca el dia anterior completo. La fecha del reporte se fija al
# arrancar: si arranca antes de esta hora (00:00 a 05:59 por defecto) es el dia anterior; despues, es hoy.
HORA_CORTE_FECHA = int(os.getenv("HORA_CORTE_FECHA", "6"))

DEBUG_HTML = _bool("DEBUG_HTML", False)
DEBUG_RETENCION_DIAS = int(os.getenv("DEBUG_RETENCION_DIAS", "7"))
DEBUG_DIR = BASE_DIR / "debug"
LOG_DIR = BASE_DIR / "logs"

# Mail (Ethereal en testing). SMTP_SECURE=false -> puerto 587 con STARTTLS obligatorio; true -> SSL (465)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")
SMTP_SECURE = _bool("SMTP_SECURE", False)
SMTP_TO = [d.strip() for d in os.getenv("SMTP_TO", "").split(",") if d.strip()]
MAIL_ASUNTO = os.getenv("MAIL_ASUNTO", "Reportes Traxion")
