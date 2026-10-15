"""Mail con los reportes: adjunta los que salieron y explica los que fallaron. Todo sale del .env."""
import mimetypes
import smtplib
import ssl
from datetime import date, datetime
from email.message import EmailMessage

import config
from reportes import Resultado
from traxion import BotError, log


def _tamanio(bytes_: int) -> str:
    if bytes_ < 1024:
        return f"{bytes_} bytes"
    if bytes_ < 1024 * 1024:
        return f"{bytes_ / 1024:,.0f} KB"
    return f"{bytes_ / 1024 / 1024:,.1f} MB"


def _registros(n: int | None) -> str:
    if n is None:
        return ""
    if n == 0:
        return ", sin movimientos"
    miles = f"{n:,}".replace(",", ".")
    return f", {miles} registro{'s' if n != 1 else ''}"


def armar(fecha: date, resultados: list[Resultado], inicio: datetime, fin: datetime) -> EmailMessage:
    ok = [r for r in resultados if r.archivo is not None]
    fallidos = [r for r in resultados if r.archivo is None]

    asunto = f"{config.MAIL_ASUNTO} {fecha:%d/%m/%Y}"
    if fallidos:
        asunto += " - CON ERRORES"

    lineas = [f"Reportes de Traxion del {fecha:%d/%m/%Y} (corrida del {inicio:%d/%m %H:%M} al {fin:%d/%m %H:%M}).", ""]
    if ok:
        lineas.append("Generados (van adjuntos):")
        lineas += [f"  - {r.nombre}: {r.archivo.name} ({_tamanio(r.archivo.stat().st_size)}{_registros(r.registros)})"
                   for r in ok]
        lineas.append("")
    if fallidos:
        lineas.append("No se pudieron generar:")
        lineas += [f"  - {r.nombre}: {r.error}" for r in fallidos]
        lineas.append("")
    if not resultados:
        lineas += ["No se generó ningún reporte.", ""]
    lineas.append("Mail automático del bot de extracción de reportes.")

    msg = EmailMessage()
    msg["From"] = config.SMTP_FROM
    msg["To"] = ", ".join(config.SMTP_TO)
    msg["Subject"] = asunto
    msg.set_content("\n".join(lineas))
    for r in ok:
        tipo, _ = mimetypes.guess_type(r.archivo.name)
        principal, sub = (tipo or "application/octet-stream").split("/", 1)
        msg.add_attachment(r.archivo.read_bytes(), maintype=principal, subtype=sub, filename=r.archivo.name)
    return msg


def enviar(msg: EmailMessage) -> None:
    faltan = [n for n in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "SMTP_FROM") if not getattr(config, n)]
    if not config.SMTP_TO:
        faltan.append("SMTP_TO")
    if faltan:
        raise BotError(f"Mail: faltan en el .env {', '.join(faltan)}")

    contexto = ssl.create_default_context()
    try:
        if config.SMTP_SECURE:
            with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=contexto, timeout=60) as s:
                s.login(config.SMTP_USER, config.SMTP_PASS)
                s.send_message(msg)
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=60) as s:
                s.starttls(context=contexto)  # nunca mandar la clave sin cifrar
                s.login(config.SMTP_USER, config.SMTP_PASS)
                s.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise BotError(f"Mail: {config.SMTP_HOST} rechazo SMTP_USER/SMTP_PASS ({e.smtp_code}). Son el usuario "
                       "y la clave de la cuenta SMTP (no los destinatarios, que van en SMTP_TO)") from None
    log(f"Mail enviado a {', '.join(config.SMTP_TO)}: {msg['Subject']}")
