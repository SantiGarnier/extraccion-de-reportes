"""
Piezas para operar Traxion (app Seaside): errores, log, debug, espera del ajaxifier, login y logout.
Lo de login, espera y logout viene del bot `automatizacion-traxion`, probado contra el Traxion real.
"""
import re
from datetime import datetime
from pathlib import Path

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


# --- Pantallas (HTML real inspeccionado en testing el 2026-10-15) ---

def ir_a(page: Page, seccion: str, item: str, titulo: str) -> None:
    """
    Menu lateral -> seccion (GESTORES, FINANCIERO, REPORTES) -> item. El item se busca DENTRO de la
    seccion: hay items con el mismo nombre en secciones distintas. La seccion solo despliega el submenu
    en el navegador; si ya esta abierto no se clickea, porque clickearla lo cerraria.
    """
    if es_pantalla_login(page):
        raise SesionVencida("La sesion vencio (la pagina muestra el login)")
    li = page.locator(
        "xpath=//ul[contains(@class,'page-sidebar-menu')]/li[contains(@class,'nav-item')]"
        f"[a/span[contains(@class,'title') and normalize-space()='{seccion}']]").first
    link = li.locator(f"xpath=./ul[contains(@class,'sub-menu')]/li/a[normalize-space()='{item}']").first
    if not link.count():
        raise BotError(f"El menu no tiene {seccion} > {item}")
    if not link.is_visible():
        li.locator("xpath=./a").click()
        link.wait_for(state="visible")
    click_y_esperar(page, link, f"Abrir {seccion} > {item}")
    verificar_titulo(page, titulo)


def verificar_titulo(page: Page, titulo: str) -> None:
    h1 = page.locator("h1.page-title").first
    actual = " ".join(h1.inner_text().split()) if h1.count() else "(sin titulo)"
    if actual != titulo:
        raise BotError(f"Se esperaba la pantalla '{titulo}' y aparecio '{actual}'")


def abrir_pestania(page: Page, nombre: str, campo_esperado: str) -> None:
    """
    Pestania jQuery UI. Su contenido carga aparte: puede verse seleccionada pero vacia un rato, asi que
    se espera a que aparezca un campo propio de esa pestania (`campo_esperado`, el texto de su label).
    """
    pestania = page.locator(".ui-tabs-nav li", has_text=re.compile(rf"^\s*{re.escape(nombre)}\s*$")).first
    if not pestania.count():
        raise BotError(f"No aparecio la pestania '{nombre}'")
    if "ui-tabs-active" not in (pestania.get_attribute("class") or ""):
        pestania.locator("a").click()
    try:
        grupo(page, campo_esperado).wait_for(state="visible")
    except PWTimeout:
        raise SinRespuesta(f"La pestania '{nombre}' no termino de cargar ('{campo_esperado}' no aparecio)") from None


def grupo(page: Page, label: str):
    """El .form-group VISIBLE cuyo label es `label` (con o sin ':' al final). Hay copias ocultas en otras pestanias."""
    etiqueta = page.locator("label.control-label", has_text=re.compile(rf"^\s*{re.escape(label)}\s*:?\s*$"))
    return page.locator(".form-group", has=etiqueta).filter(visible=True).first


def marcar_botones(page: Page, label: str, textos: list[str]) -> None:
    """
    Botones de Bootstrap (data-toggle="buttons"): se clickea el <label>; marcado = clase 'active' y el
    checkbox 'checked'. Un click sobre uno marcado lo DESMARCA: se mira el estado antes de clickear.
    """
    g = grupo(page, label)
    if not g.count():
        raise BotError(f"No aparecio el bloque '{label}'")
    for texto in textos:
        boton = g.locator("label.btn", has_text=re.compile(rf"^\s*{re.escape(texto)}\s*$"))
        if boton.count() != 1:
            raise BotError(f"'{label}': se esperaba un boton '{texto}' y hay {boton.count()}")
        if not _marcado(boton):
            boton.click()
            page.wait_for_function("el => el.classList.contains('active') && el.querySelector('input').checked",
                                   arg=boton.element_handle(), timeout=5000)
        if not _marcado(boton):
            raise BotError(f"'{label}': no se pudo marcar '{texto}'")


def _marcado(boton) -> bool:
    return boton.evaluate("el => el.classList.contains('active') && el.querySelector('input').checked")


def poner_valor(page: Page, label: str, valor: str, aceptables: tuple[str, ...] = ()) -> None:
    """
    Carga un campo de texto (fecha dd/mm/aaaa u hora). Si ya tiene el valor (o uno equivalente, como
    '0:00:00' por '00:00:00') no se toca. Despues verifica que el campo haya quedado con ese valor.
    """
    campo = grupo(page, label).locator("input:not([type=hidden])").first
    if campo.input_value() in (valor, *aceptables):
        return
    campo.fill(valor)
    # bootstrap-datepicker guarda la fecha aparte del texto: si no se le avisa, al cerrarse vuelve a
    # escribir la fecha que tenia (paso en testing el 2026-10-16). Se le carga el valor por su API y se
    # cierra el desplegable para que no tape "Buscar". Lo mismo con el reloj (timepicker).
    page.evaluate("""([el, v]) => {
        const $ = window.jQuery;
        if ($ && $(el).data('datepicker')) { $(el).datepicker('update', v); $(el).datepicker('hide'); }
        if ($ && $(el).data('timepicker')) { $(el).timepicker('setTime', v); }
        el.dispatchEvent(new Event('change', {bubbles: true}));
    }""", [campo.element_handle(), valor])
    if campo.input_value() not in (valor, *aceptables):
        raise BotError(f"'{label}' quedo en '{campo.input_value()}' en vez de '{valor}'")


def buscar(page: Page, accion: str, timeout: int | None = None) -> int:
    """Clickea "Buscar" y devuelve la cantidad de la grilla ("Datos: N")."""
    boton = page.get_by_role("button", name="Buscar", exact=True).filter(visible=True).first
    click_y_esperar(page, boton, f"{accion}: Buscar", timeout=timeout)
    return cantidad_de_datos(page, accion)


def cantidad_de_datos(page: Page, accion: str) -> int:
    for texto in page.locator(".caption").all_inner_texts():
        m = re.search(r"Datos:\s*([\d.]+)", texto)
        if m:
            return int(m.group(1).replace(".", ""))
    # "No pude leer" no es "no hay datos": es un error del bot
    raise BotError(f"{accion}: no se pudo leer la cantidad de datos de la grilla")


def exportar_excel(page: Page, destino: Path, accion: str, columnas: list[str],
                   timeout: int | None = None) -> Path:
    """
    Funciones -> "Exportar a Excel". Es un link comun (no pasa por el ajaxifier): el servidor contesta
    con un adjunto (en testing, un CSV). En el mismo menu hay acciones peligrosas (Suspender, Anular,
    Confirmar marcados...): se clickea SOLO el item con texto exacto "Exportar a Excel".
    `destino` va sin extension: se usa la del archivo que manda Traxion.
    """
    # Despues de "Buscar" la barra de la grilla puede aparecer duplicada (en Cuentas hubo 2 "Funciones"
    # visibles el 2026-10-16): se usa la primera cuyo menu tenga exactamente un "Exportar a Excel".
    candidatos = page.locator("a.dropdown-toogle", has_text=re.compile(r"^\s*Funciones\s*$")).filter(visible=True)
    funciones = item = None
    for f in candidatos.all():
        items = f.locator("xpath=..").locator(".dropdown-menu a").filter(
            has_text=re.compile(r"^\s*Exportar a Excel\s*$"))
        if items.count() == 1:
            funciones, item = f, items
            break
    if item is None:
        raise BotError(f"{accion}: no aparecio 'Funciones' con un item 'Exportar a Excel' "
                       f"({candidatos.count()} boton(es) 'Funciones' visibles)")
    if candidatos.count() > 1:
        log(f"  {accion}: hay {candidatos.count()} botones 'Funciones' visibles; se usa el primero con 'Exportar a Excel'")
    if not item.is_visible():
        funciones.click()
        item.wait_for(state="visible")

    inicio = datetime.now()
    try:
        with page.expect_download(timeout=timeout) as info:
            item.click()
    except PWTimeout:
        ms = timeout if timeout is not None else config.TIMEOUT_MS
        raise SinRespuesta(f"{accion}: la exportacion no bajo ningun archivo en {ms / 1000:g} s") from None
    descarga = info.value
    if descarga.failure():
        raise BotError(f"{accion}: fallo la descarga ({descarga.failure()})")
    archivo = destino.with_name(destino.name + (Path(descarga.suggested_filename).suffix or ".csv"))
    descarga.save_as(archivo)
    log(f"  {accion}: bajo '{descarga.suggested_filename}' -> {archivo.name} "
        f"({archivo.stat().st_size} bytes, {(datetime.now() - inicio).total_seconds():.0f} s)")
    verificar_archivo(archivo, accion, columnas)
    return archivo


def verificar_archivo(archivo: Path, accion: str, columnas: list[str]) -> None:
    """Que no este vacio, que no sea una pagina HTML (error o login) y que tenga el encabezado esperado."""
    datos = archivo.read_bytes()
    if not datos.strip():
        raise BotError(f"{accion}: el archivo exportado esta vacio")
    if datos.lstrip()[:1] == b"<":
        raise BotError(f"{accion}: en vez del reporte llego una pagina HTML")
    encabezado = [c.strip().strip('"') for c in datos.decode("iso-8859-1").splitlines()[0].split(";")]
    faltan = [c for c in columnas if c not in encabezado]
    if faltan:
        raise BotError(f"{accion}: al archivo le faltan las columnas {faltan}")
