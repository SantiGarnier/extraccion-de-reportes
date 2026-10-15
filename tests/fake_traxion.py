"""
Traxion de mentira para las pruebas: se sirve con `context.route`, sin red.
Imita lo que importa del real: el ajaxifier (POST con X-Requested-With: Ajaxifier que reemplaza
todo el <body>), el overlay .blockUI, inputs con name numerico, el menu GESTORES y el logout con
una copia oculta de "Salir de plataforma" (menu para celular) antes de la real.
"""
from urllib.parse import parse_qs, urlparse

URL = "http://traxion.test/"
USUARIO = "operador"
CLAVE = "clave-de-prueba"

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


_HOME = f"""
<div style="display:none"><a href="#" data-ajax="/salir">Salir de plataforma</a></div>
<ul class="nav navbar-nav pull-right"><li class="dropdown">
  <a href="#" class="dropdown-toggle" data-toggle="dropdown">{USUARIO}</a>
  <ul class="dropdown-menu" style="display:none"><li><a href="#" data-ajax="/salir">Salir de plataforma</a></li></ul>
</li></ul>
<ul class="page-sidebar-menu">
  <li class="nav-item"><a href="javascript:;" disable_ajaxifier><span class="title">GESTORES</span></a>
    <ul class="sub-menu" style="display:none"><li><a href="#" data-ajax="/cuentas">Cuentas</a></li></ul></li>
</ul>
<a href="#" id="vencida" data-ajax="/vencida">Vencida</a>
<a href="#" id="lenta" data-ajax="/lenta">Lenta</a>
<a href="#" id="rompe" data-ajax="/rompe">Rompe</a>
"""

_CONFIRMAR_SALIDA = """<h3>¿Desea cerrar la plataforma?</h3>
<button type="button" data-ajax="/salir/si">Salir</button>
<button type="button" data-ajax="/home">Cancelar</button>"""


class FakeTraxion:
    """Registra los pedidos AJAX que recibe (`self.pedidos`) para que las pruebas los verifiquen."""

    def __init__(self):
        self.pedidos: list[str] = []
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
            return route.fulfill(content_type="text/html",
                                 body=f"<!doctype html><html>{_HEAD}<body>{_login()}</body></html>")
        self.pedidos.append(ruta)
        if ruta == "/lenta":
            self._colgados.append(route)  # no responde hasta `liberar()`
            return
        if ruta == "/rompe":
            return route.fulfill(status=500, content_type="text/html", body="<h1>Error interno</h1>")
        route.fulfill(content_type="text/html", body=self._cuerpo(ruta, req.post_data or ""))

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
        return _HOME
