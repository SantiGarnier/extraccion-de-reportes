"""
Traxion de mentira para las pruebas: se sirve con `context.route`, sin red.
Imita lo que importa del real (HTML inspeccionado en testing el 2026-10-15):
- el ajaxifier (POST con X-Requested-With: Ajaxifier que reemplaza todo el <body>) y el overlay .blockUI;
- el menu lateral de dos niveles, con un "Cuentas" tambien en PROVEEDORES;
- el logout con una copia oculta de "Salir de plataforma" (menu para celular) antes de la real;
- pestanias jQuery UI cuyo contenido carga aparte, y bloques repetidos (ocultos) en otras pestanias;
- botones de Bootstrap (data-toggle="buttons") que se desmarcan con un click si ya estaban marcados;
- "Funciones" con "Exportar a Excel" (link comun que baja un CSV) y acciones peligrosas al lado.
"""
from urllib.parse import parse_qs, urlparse

URL = "http://traxion.test/"
USUARIO = "operador"
CLAVE = "clave-de-prueba"
HOY = "15/10/2026"  # lo que la plataforma precarga en los campos de fecha

_HEAD = """<head><meta charset="utf-8"><title>Traxion</title>
<style>.blockUI{position:fixed;inset:0;background:#0003}</style>
<script>
document.addEventListener('click', async ev => {
  const toggle = ev.target.closest('[data-toggle=dropdown]');
  if (toggle) {
    ev.preventDefault();
    const menu = toggle.parentElement.querySelector('.dropdown-menu');
    menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
    return;
  }
  const seccion = ev.target.closest('a.nav-toggle');
  if (seccion) {
    ev.preventDefault();
    const sub = seccion.parentElement.querySelector('.sub-menu');
    sub.style.display = sub.style.display === 'none' ? 'block' : 'none';
    return;
  }
  const boton = ev.target.closest('[data-toggle=buttons] label.btn');
  if (boton) {
    const check = boton.querySelector('input[type=checkbox]');
    if (ev.target !== check) {  // click en el texto: se cambia a mano (como Bootstrap)
      ev.preventDefault();
      check.checked = !check.checked;
    }  // click justo en el checkbox: el navegador ya lo cambio
    boton.classList.toggle('active', check.checked);
    return;
  }
  const tab = ev.target.closest('.ui-tabs-nav a');
  if (tab) {
    ev.preventDefault();
    document.querySelectorAll('.ui-tabs-nav li').forEach(li => li.classList.remove('ui-tabs-active'));
    tab.parentElement.classList.add('ui-tabs-active');
    document.querySelectorAll('.ui-tabs-panel').forEach(p => p.style.display = 'none');
    const panel = document.getElementById(tab.dataset.panel);
    panel.style.display = 'block';
    if (!panel.innerHTML.trim() && panel.dataset.cargar) {  // el contenido carga aparte
      panel.innerHTML = await (await fetch(panel.dataset.cargar)).text();
    }
    return;
  }
  const el = ev.target.closest('[data-ajax]');
  if (!el) return;
  ev.preventDefault();
  const ov = document.createElement('div');
  ov.className = 'blockUI'; ov.textContent = 'Un momento por favor...';
  document.body.appendChild(ov);
  const form = el.closest('form');
  const r = await fetch(el.dataset.ajax + '?_s=SECRETO123&_k=CONT456', {
    method: 'POST', headers: {'X-Requested-With': 'Ajaxifier'},
    body: form ? new URLSearchParams(new FormData(form)) : ''});
  document.body.innerHTML = await r.text();
});
</script></head>"""


def _login(error: str = "") -> str:
    alerta = f'<div class="alert alert-danger">{error}</div>' if error else ""
    return f"""{alerta}<form>
  <input id="usuario" name="11" type="text"><input id="password" name="12" type="password">
  <button type="button" data-ajax="/login">Ingresar</button></form>"""


def _seccion(titulo: str, items: dict[str, str]) -> str:
    links = "".join(f'<li class="nav-item"><a class="nav-link" href="#" data-ajax="{ruta}">{texto}</a></li>'
                    for texto, ruta in items.items())
    return f"""<li class="nav-item"><a class="nav-link nav-toggle" href="javascript:;" disable_ajaxifier>
      <span class="title">{titulo}</span></a><ul class="sub-menu" style="display:none">{links}</ul></li>"""


_MARCO = f"""
<div style="display:none"><a href="#" data-ajax="/salir">Salir de plataforma</a></div>
<ul class="nav navbar-nav pull-right"><li class="dropdown">
  <a href="#" class="dropdown-toggle" data-toggle="dropdown">{USUARIO}</a>
  <ul class="dropdown-menu" style="display:none"><li><a href="#" data-ajax="/salir">Salir de plataforma</a></li></ul>
</li></ul>
<ul class="page-sidebar-menu">
  {_seccion("PROVEEDORES", {"Cuentas": "/proveedores/cuentas"})}
  {_seccion("GESTORES", {"Cuentas": "/cuentas", "Comisiones": "/comisiones"})}
  {_seccion("FINANCIERO", {"Solicitudes": "/solicitudes", "Depositos": "/depositos"})}
  {_seccion("REPORTES", {"Ventas": "/ventas", "Financiero": "/financiero"})}
</ul>
<div class="page-content">{{contenido}}</div>
"""

_HOME = _MARCO.replace("{contenido}", """<h1 class="page-title">Plataforma Traxion</h1>
<a href="#" id="vencida" data-ajax="/vencida">Vencida</a>
<a href="#" id="lenta" data-ajax="/lenta">Lenta</a>
<a href="#" id="rompe" data-ajax="/rompe">Rompe</a>""")

_CONFIRMAR_SALIDA = """<h3>¿Desea cerrar la plataforma?</h3>
<button type="button" data-ajax="/salir/si">Salir</button>
<button type="button" data-ajax="/home">Cancelar</button>"""


def _botones(label: str, botones: dict[str, bool], prefijo: str) -> str:
    """Bloque de botones de Bootstrap. `botones` = {texto: marcado}."""
    html = "".join(
        f'<label class="btn btn-default{" active" if marcado else ""}"><input class="toggle" type="checkbox" '
        f'name="{prefijo}{texto}"{" checked" if marcado else ""}><input type="hidden"> {texto}</label>'
        for texto, marcado in botones.items())
    return (f'<div class="form-group"><label class="control-label col-md-3">{label}</label><div class="col-md-9">'
            f'<div class="btn-group" data-toggle="buttons">{html}</div></div></div>')


def _campo(label: str, nombre: str, valor: str) -> str:
    return (f'<div class="form-group"><label class="control-label col-md-3">{label} </label>'
            f'<div class="col-md-9"><input class="bootstrap-date-picker form-control" name="{nombre}" '
            f'value="{valor}" type="text"></div></div>')


def _fechas() -> str:
    return (_campo("Desde fecha:", "desde_fecha", HOY) + _campo("Desde hora:", "desde_hora", "0:00:00")
            + _campo("Hasta fecha:", "hasta_fecha", HOY) + _campo("Hasta hora:", "hasta_hora", "23:59:59"))


_INCLUIR = ["PEI", "T.Credito", "Rec.Terceros", "Efectivo", "Depositos", "Cheques"]
# "Cheques" desmarcado para probar que el bot marca lo que falta sin desmarcar lo demas
PANEL_DEPOSITOS_FILTROS = (_fechas() + _botones("Incluir:", {t: t != "Cheques" for t in _INCLUIR}, "incluir_")
                           + _botones("Depositos:", {"Enviados": True, "Recibidos": True}, "dep_"))
PANEL_VENTAS_FILTROS = _fechas()


def _pantalla(titulo: str, pestanias: list[tuple[str, str, str]], activa: str, funciones: dict[str, str],
              datos: int, pantalla: str) -> str:
    """
    pestanias: (nombre, contenido, url_para_cargarlo). Si el contenido esta vacio, carga aparte al abrirla.
    funciones: {texto: href}. Los href '/peligro/...' son acciones AJAX que no se deben tocar nunca.
    """
    nav = "".join(f'<li class="ui-tabs-tab{" ui-tabs-active" if n == activa else ""}">'
                  f'<a disable_ajaxifier href="#" data-panel="panel-{i}">{n}</a></li>'
                  for i, (n, _, _) in enumerate(pestanias))
    paneles = "".join(f'<div id="panel-{i}" class="ui-tabs-panel" data-cargar="{url}" '
                      f'style="display:{"block" if n == activa else "none"}">{contenido}</div>'
                      for i, (n, contenido, url) in enumerate(pestanias))
    items = "".join(
        f'<li><a href="#" data-ajax="{href}">{texto}</a></li>' if href.startswith("/peligro")
        else f'<li><a disable_ajaxifier href="{href}"><i class="fa fa-file-text"></i>{texto}</a></li>'
        for texto, href in funciones.items())
    contenido = f"""<h1 class="page-title">{titulo}</h1>
<form><div class="ui-tabs"><ul class="ui-tabs-nav">{nav}</ul>{paneles}</div>
<input class="btn blue" type="submit" value="Buscar" data-ajax="/buscar/{pantalla}">
<input class="btn red" type="submit" value="Limpiar" data-ajax="/{pantalla}"></form>
<div class="caption">Filtros</div><div class="caption">Datos: {datos}</div>
<div class="btn-group"><a class="btn btn-sm purple dropdown-toogle" data-toggle="dropdown">
  <i class="icon-settings"></i><span class="details">Funciones</span></a>
  <ul class="dropdown-menu" style="display:none">{items}</ul></div>"""
    return _MARCO.replace("{contenido}", contenido)


def _cuentas(datos: int) -> str:
    mostrar = _botones("Mostrar", {"Cta.Cte.": True, "Saldo Disponible": False, "Saldo Virtual": False,
                                   "Arbol": False}, "mostrar_")
    return _pantalla("Cuentas", [("General", mostrar, ""), ("Usuario", "", "/pestania/usuario")], "General",
                     {"Exportar a Excel": "/exportar/cuentas", "Exportar datos red": "/exportar/red",
                      "Suspender marcados": "/peligro/suspender", "Activar marcados": "/peligro/activar"},
                     datos, "cuentas")


def _depositos(datos: int, buscado: bool) -> str:
    hoy = _botones("Incluir:", {t: True for t in _INCLUIR}, "hoy_incluir_")
    filtros = ("Por Filtros", PANEL_DEPOSITOS_FILTROS if buscado else "", "/pestania/depositos")
    return _pantalla("Administracion de Depositos", [("Hoy", hoy, ""), filtros],
                     "Por Filtros" if buscado else "Hoy",
                     {"Exportar a Excel": "/exportar/depositos", "Confirmar marcados": "/peligro/confirmar",
                      "Anular marcados": "/peligro/anular", "Exportar depositos": "/exportar/otro"},
                     datos, "depositos")


def _ventas(datos: int, buscado: bool) -> str:
    filtros = ("Por Filtros", PANEL_VENTAS_FILTROS if buscado else "", "/pestania/ventas")
    return _pantalla("Consulta de Ventas", [("Resumen Hoy", "<p>Resumen</p>", ""), filtros],
                     "Por Filtros" if buscado else "Resumen Hoy",
                     {"Exportar a Excel": "/exportar/ventas", "Exportar a PDF": "/exportar/pdf"}, datos, "ventas")


# Lo que baja cada "Exportar a Excel" (nombre del adjunto, contenido). En el real llegan en ISO-8859-1.
EXPORTES = {
    "cuentas": ("Cuentas Comerciales.csv",
                ";Numero;Nombre;Tipo;Estado;Homolog;Padre;Cta.Cte.;Saldo Disponible;Saldo Virtual;\n"
                ";1;Cuenta Uno;Punto de venta;Abierta;;Red;10,00;5,00;0,00;\n;;;;;;;10,00;5,00;0,00;\n"),
    "depositos": ("reporte.csv",
                  ";Fecha;F.Dep.;Tipo;Nro.Ope.;Cuenta;Contraparte;Usuario;Importe;Estado;\n;;;;;;;;;;\n"),
    "ventas": ("Pagos.csv",
               "Nro.Ope.;Fecha;Emp;Usuario;Tipo Operacion;Producto;Estado;Modo;Importe;\n"
               "1;15/10/2026 - 10:00:00;Empresa;usr;Pago;Producto Ñandú;Confirmada;WEB;100,00;\n;;;;;;;;100,00;\n"),
}
DATOS = {"cuentas": 258, "depositos": 0, "ventas": 3}


class FakeTraxion:
    """Registra los pedidos AJAX (`pedidos`), las descargas (`exportes`) y los formularios de "Buscar" (`busquedas`)."""

    def __init__(self):
        self.pedidos: list[str] = []
        self.exportes: list[str] = []
        self.busquedas: dict[str, dict[str, str]] = {}
        self.exporte_roto: str | None = None  # pantalla cuyo exporte devuelve una pagina HTML
        self._colgados = []

    def instalar(self, context) -> None:
        context.route(URL + "**", self._atender)

    def liberar(self) -> None:
        """Corta los pedidos que quedaron sin responder (si no, Playwright se queja al cerrar)."""
        for route in self._colgados:
            route.abort()
        self._colgados.clear()

    def _atender(self, route) -> None:
        req = route.request
        ruta = urlparse(req.url).path
        if req.method == "GET":
            return self._get(route, ruta)
        self.pedidos.append(ruta)
        if ruta == "/lenta":
            self._colgados.append(route)  # no responde hasta `liberar()`
            return
        if ruta == "/rompe":
            return route.fulfill(status=500, content_type="text/html", body="<h1>Error interno</h1>")
        route.fulfill(content_type="text/html", body=self._cuerpo(ruta, req.post_data or ""))

    def _get(self, route, ruta: str) -> None:
        if ruta.startswith("/pestania/"):
            panel = {"depositos": PANEL_DEPOSITOS_FILTROS, "ventas": PANEL_VENTAS_FILTROS}.get(ruta[10:], "")
            return route.fulfill(content_type="text/html", body=panel)
        if ruta.startswith("/exportar/"):
            pantalla = ruta[10:]
            self.exportes.append(pantalla)
            if pantalla == self.exporte_roto:
                return route.fulfill(content_type="text/html", body="<html><body>Error</body></html>",
                                     headers={"Content-Disposition": 'attachment; filename="reporte.csv"'})
            nombre, contenido = EXPORTES.get(pantalla, ("otro.csv", "x;y\n"))
            return route.fulfill(body=contenido.encode("iso-8859-1"), headers={
                "Content-Type": "application/csv", "Content-Disposition": f'attachment; filename="{nombre}"'})
        route.fulfill(content_type="text/html", body=f"<!doctype html><html>{_HEAD}<body>{_login()}</body></html>")

    def _cuerpo(self, ruta: str, datos: str) -> str:
        if ruta == "/login":
            campos = parse_qs(datos)
            if campos.get("11") == [USUARIO] and campos.get("12") == [CLAVE]:
                return _HOME
            return _login("Usuario o clave incorrectos")
        if ruta == "/salir":
            return _CONFIRMAR_SALIDA
        if ruta in ("/salir/si", "/vencida"):
            return _login()
        pantallas = {"cuentas": lambda n, b: _cuentas(n), "depositos": _depositos, "ventas": _ventas}
        nombre = ruta.strip("/").split("/")[-1]
        if ruta.startswith("/buscar/"):
            self.busquedas[nombre] = {k: v[-1] for k, v in parse_qs(datos, keep_blank_values=True).items()}
            return pantallas[nombre](DATOS[nombre], True)
        if ruta.strip("/") in pantallas:
            return pantallas[nombre](0, False)
        return _HOME
