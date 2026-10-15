"""
Piezas para operar Traxion (app Seaside): errores, log, debug, espera del ajaxifier, login y logout.
Lo de login, espera y logout viene del bot `automatizacion-traxion`, probado contra el Traxion real.
"""
import re
from datetime import datetime

from playwright.sync_api import BrowserContext, Page, TimeoutError as PWTimeout

import config


class BotError(Exception):
    estado = "ERROR"


class SinRespuesta(BotError):
    """La plataforma no reemplazo la pagina dentro del tope (queda 'loading')."""


class SesionVencida(BotError):
    """Despues de un click aparecio la pantalla de login."""


# _s (sesion) y _k (continuacion) de Seaside: con ellos alguien podria entrar como el operador.
_PARAMS_SESION = re.compile(r"\b(_[sk]=)[^&\"'\s<>]+")


def tapar_sesion(texto: str) -> str:
    """Reemplaza los valores de _s y _k por REDACTADO (logs, mensajes de error, HTML de debug)."""
    return _PARAMS_SESION.sub(r"\1REDACTADO", texto)


def log(msg: str) -> None:
    linea = f"[{datetime.now():%H:%M:%S}] {tapar_sesion(msg)}"
    print(linea, flush=True)
    try:
        config.LOG_DIR.mkdir(exist_ok=True)
        with open(config.LOG_DIR / f"bot_{datetime.now():%Y%m%d}.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d} {linea}\n")
    except OSError:
        pass  # que un problema con el archivo de log nunca frene el bot


def guardar_debug(page: Page, etiqueta: str) -> None:
    """Captura ante un error (no lleva la URL -> no lleva la sesion). HTML solo con DEBUG_HTML=true."""
    config.DEBUG_DIR.mkdir(exist_ok=True)
    etiqueta = re.sub(r"[^\w.-]", "_", etiqueta)[:80]
    base = config.DEBUG_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{etiqueta}"
    try:
        page.screenshot(path=f"{base}.png", full_page=True)
        if config.DEBUG_HTML:
            base.with_suffix(".html").write_text(tapar_sesion(page.content()), encoding="utf-8")
        log(f"Debug guardado en {base}.png" + (" / .html" if config.DEBUG_HTML else ""))
    except Exception as e:  # noqa: BLE001 - el debug nunca debe tapar el error original
        log(f"No se pudo guardar debug: {e}")


def limpiar_debug() -> None:
    """Borra de debug/ lo que tenga mas de DEBUG_RETENCION_DIAS (las capturas pueden tener datos personales)."""
    if not config.DEBUG_DIR.exists():
        return
    limite = datetime.now().timestamp() - config.DEBUG_RETENCION_DIAS * 86400
    for archivo in config.DEBUG_DIR.iterdir():
        try:
            if archivo.is_file() and archivo.stat().st_mtime < limite:
                archivo.unlink()
        except OSError:
            pass


def mensajes_visibles(page: Page) -> list[str]:
    """Textos de alertas/notificaciones visibles (errores de login, confirmaciones, etc.)."""
    selector = ".alert, .jGrowl-notification, .sweet-alert, .help-block, .text-danger, .ui-dialog, .toast"
    textos = []
    for el in page.locator(selector).all():
        try:
            if el.is_visible():
                t = el.inner_text().strip()
                if t:
                    textos.append(" ".join(t.split()))
        except Exception:  # noqa: BLE001
            pass
    return textos


_MARCA_ID = "__bot_marca"


def click_y_esperar(page: Page, elemento, accion: str, timeout: int | None = None,
                    error_cls: type[SinRespuesta] = SinRespuesta, chequear_sesion: bool = True,
                    directo: bool = False) -> None:
    """
    Clickea y espera a que la plataforma reemplace la pagina, por evento y no por tiempo:
      1. Antes del click se inserta un <div> marcador dentro del <body>.
      2. El ajaxifier, al recibir la respuesta, hace $("body").html(...) -> el marcador desaparece.
         (Si en vez de AJAX hubiera una navegacion completa, el marcador tambien desaparece.)
      3. Apenas el marcador no existe mas, la pagina nueva ya esta en el DOM y se sigue.
    `timeout` es el tope (por defecto TIMEOUT_MS); si se cumple sin respuesta se lanza `error_cls`.
    Si la pagina nueva es el login, la sesion vencio -> SesionVencida.
    directo=True dispara el click por JS aunque el elemento no este visible.
    """
    page.evaluate(
        "id => { const d = document.createElement('div'); d.id = id; d.hidden = true; document.body.appendChild(d); }",
        _MARCA_ID,
    )
    respuestas = []

    def _capturar(resp):
        if resp.request.headers.get("x-requested-with") == "Ajaxifier":
            respuestas.append(resp)

    page.on("response", _capturar)
    try:
        if directo:
            elemento.dispatch_event("click", timeout=timeout)
        else:
            elemento.click()
        page.wait_for_function(f"() => !document.getElementById('{_MARCA_ID}')", timeout=timeout)
    except PWTimeout:
        ms = timeout if timeout is not None else config.TIMEOUT_MS
        raise error_cls(f"{accion}: la plataforma no respondio en {ms / 1000:g} s") from None
    finally:
        page.remove_listener("response", _capturar)

    if respuestas and respuestas[-1].status >= 400:
        raise BotError(f"{accion}: el servidor respondio HTTP {respuestas[-1].status}")
    if chequear_sesion and es_pantalla_login(page):
        raise SesionVencida(f"{accion}: la sesion vencio (aparecio el login)")
    # el overlay "Un momento por favor..." (blockUI) se va con el body viejo; por las dudas
    page.locator(".blockUI").first.wait_for(state="detached")


def es_pantalla_login(page: Page) -> bool:
    return bool(page.locator("#usuario").count() and page.locator("#password").count()
                and page.get_by_role("button", name="Ingresar").count())


class Sesion:
    """La pagina logueada. Se puede descartar y volver a loguear cuando queda en mal estado."""

    def __init__(self, context: BrowserContext):
        self.context = context
        self.page: Page | None = None

    def iniciar(self) -> None:
        self.terminar(timeout=5000)  # la pagina anterior puede estar trabada: tope corto para el logout
        self.page = self.context.new_page()
        # confirm()/alert() de JS: Playwright los cancela por defecto; los aceptamos y los logueamos
        self.page.on("dialog", lambda d: (log(f"Dialogo JS: {d.message!r} -> aceptar"), d.accept()))
        login(self.page)

    def terminar(self, timeout: int = 15000) -> None:
        """Cierra la sesion en Traxion (si se puede) y la pagina. Nunca deja una sesion viva al descartarla."""
        if self.page is None:
            return
        cerrar_sesion_traxion(self.page, timeout)
        try:
            self.page.close()
        except Exception:  # noqa: BLE001
            pass
        self.page = None


def login(page: Page) -> None:
    if not config.TRAXION_USER or not config.TRAXION_PASS:
        raise BotError("Faltan TRAXION_USER / TRAXION_PASS en el .env")
    log(f"Abriendo {config.TRAXION_URL}")
    page.goto(config.TRAXION_URL, wait_until="domcontentloaded")
    page.locator("#usuario").wait_for(state="visible")

    page.locator("#usuario").fill(config.TRAXION_USER)
    page.locator("#password").fill(config.TRAXION_PASS)
    click_y_esperar(page, page.get_by_role("button", name="Ingresar"), "Login", chequear_sesion=False)

    # La pagina ya cambio: si no esta el menu GESTORES, el login fallo
    if not page.get_by_text("GESTORES", exact=True).count():
        if page.locator("iframe[src*='recaptcha']").count():
            raise BotError("La plataforma pidio captcha. Hay que resolverlo a mano; el bot no lo saltea.")
        detalle = " | ".join(mensajes_visibles(page)) or "sin mensaje visible"
        raise BotError(f"Login fallido ({detalle})")

    log(f"Login OK como '{config.TRAXION_USER}'")


def cerrar_sesion_traxion(page: Page, timeout: int = 15000) -> None:
    """
    Menu del usuario -> "Salir de plataforma" -> "Salir". Cerrar el navegador NO alcanza.
    Best effort: si falla, avisa (con el paso y una captura) y sigue. Solo usa elementos VISIBLES:
    la pagina tiene copias ocultas (menu para celular) antes de las reales.
    """
    paso = "revisar la pagina"
    try:
        # about:blank: el login corto antes de abrir Traxion, no hay sesion que cerrar
        if page.is_closed() or page.url == "about:blank" or es_pantalla_login(page):
            return
        salir_menu = page.get_by_text("Salir de plataforma", exact=True)
        if not salir_menu.count():
            raise BotError("la pagina no tiene el link 'Salir de plataforma'")
        if not salir_menu.filter(visible=True).count():
            paso = "abrir el menu del usuario"
            abrir_menu_usuario(page, salir_menu, timeout)
        paso = "Salir de plataforma"
        if salir_menu.filter(visible=True).count():
            click_y_esperar(page, salir_menu.filter(visible=True).first, "Cerrar sesion (menu)",
                            timeout=timeout, chequear_sesion=False)
        else:
            # El desplegable no se abrio: el link igual esta en la pagina, oculto; se lo activa directo
            log("  El menu del usuario no se desplego: se activa 'Salir de plataforma' directo")
            click_y_esperar(page, salir_menu.first, "Cerrar sesion (menu)", timeout=timeout,
                            chequear_sesion=False, directo=True)
        if not es_pantalla_login(page):  # si la confirmacion fue un confirm() de JS, ya esta en el login
            paso = "confirmar la salida"
            confirmar = page.get_by_role("button", name="Salir", exact=True).or_(
                page.get_by_role("link", name="Salir", exact=True)).filter(visible=True).first
            confirmar.wait_for(state="visible", timeout=timeout)
            click_y_esperar(page, confirmar, "Cerrar sesion (confirmar)", timeout=timeout, chequear_sesion=False)
        if es_pantalla_login(page):
            log("Sesion de Traxion cerrada")
        else:
            log("AVISO: se confirmo la salida de Traxion pero no aparecio el login")
    except Exception as e:  # noqa: BLE001 - cerrar sesion nunca debe tapar el resultado del lote
        log(f"AVISO: no se pudo cerrar la sesion de Traxion en el paso '{paso}' "
            f"({str(e).splitlines()[0][:150]}); vence sola")
        if not page.is_closed():
            guardar_debug(page, f"logout_error_{paso}")


def abrir_menu_usuario(page: Page, salir_menu, timeout: int) -> None:
    """Despliega el menu que contiene "Salir de plataforma" (no lanza error si no se abre)."""
    boton = page.locator(".dropdown", has=salir_menu).locator(
        ".dropdown-toggle, [data-toggle='dropdown'], [data-bs-toggle='dropdown']").filter(visible=True)
    if not boton.count():
        usuario = re.compile(rf"^\s*{re.escape(config.TRAXION_USER)}\s*$")
        boton = page.locator("a", has_text=usuario).filter(visible=True)
    if not boton.count():
        return
    try:
        boton.first.click(timeout=timeout)
        salir_menu.filter(visible=True).first.wait_for(state="visible", timeout=min(timeout, 3000))
    except PWTimeout:
        pass
