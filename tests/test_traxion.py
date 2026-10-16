"""
Pruebas de login, espera del ajaxifier y logout contra el Traxion de mentira (Chromium headless real).
Correr desde la raiz del repo:  python -m unittest -v
"""
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from playwright.sync_api import sync_playwright

import config
import reportes
import traxion
from tests import fake_traxion
from tests.fake_traxion import CLAVE, URL, USUARIO, FakeTraxion


class TestTaparSesion(unittest.TestCase):
    def test_tapa_s_y_k(self):
        texto = "https://x/?_s=abc123&_k=def456&otro=1"
        self.assertEqual(traxion.tapar_sesion(texto), "https://x/?_s=REDACTADO&_k=REDACTADO&otro=1")

    def test_no_toca_lo_demas(self):
        self.assertEqual(traxion.tapar_sesion("mis_saldos=10"), "mis_saldos=10")


class TestContraTraxionFalso(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.config = mock.patch.multiple(
            config, TRAXION_URL=URL, TRAXION_USER=USUARIO, TRAXION_PASS=CLAVE,
            LOG_DIR=tmp / "logs", DEBUG_DIR=tmp / "debug", DEBUG_HTML=False, TIMEOUT_MS=10000)
        self.config.start()
        self.context = self.browser.new_context(viewport={"width": 1600, "height": 1000}, locale="es-AR")
        self.context.set_default_timeout(config.TIMEOUT_MS)
        self.traxion = FakeTraxion()
        self.traxion.instalar(self.context)
        self.sesion = traxion.Sesion(self.context)

    def tearDown(self):
        self.sesion.terminar(timeout=3000)
        self.traxion.liberar()
        self.context.close()
        self.config.stop()
        self.tmp.cleanup()

    def leer_log(self) -> str:
        return "".join(p.read_text(encoding="utf-8") for p in config.LOG_DIR.glob("*.log"))

    def test_login_y_logout_por_el_menu_visible(self):
        self.sesion.iniciar()
        page = self.sesion.page
        self.assertTrue(page.get_by_text("GESTORES", exact=True).count())

        self.sesion.terminar()
        self.assertEqual(self.traxion.pedidos, ["/login", "/salir", "/salir/si"])
        self.assertIn("Sesion de Traxion cerrada", self.leer_log())

    def test_login_fallido_muestra_el_mensaje(self):
        with mock.patch.object(config, "TRAXION_PASS", "otra"):
            with self.assertRaisesRegex(traxion.BotError, "Usuario o clave incorrectos"):
                self.sesion.iniciar()

    def test_sin_credenciales_no_intenta(self):
        with mock.patch.object(config, "TRAXION_USER", ""):
            with self.assertRaisesRegex(traxion.BotError, "Faltan TRAXION_USER"):
                self.sesion.iniciar()
        self.assertEqual(self.traxion.pedidos, [])

    def test_sesion_vencida(self):
        self.sesion.iniciar()
        page = self.sesion.page
        with self.assertRaises(traxion.SesionVencida):
            traxion.click_y_esperar(page, page.locator("#vencida"), "Ir a algo")

    def test_sin_respuesta_corta_en_el_tope(self):
        self.sesion.iniciar()
        page = self.sesion.page
        with self.assertRaisesRegex(traxion.SinRespuesta, "no respondio en 1 s"):
            traxion.click_y_esperar(page, page.locator("#lenta"), "Buscar", timeout=1000)

    def test_http_500_es_error(self):
        self.sesion.iniciar()
        page = self.sesion.page
        with self.assertRaisesRegex(traxion.BotError, "HTTP 500"):
            traxion.click_y_esperar(page, page.locator("#rompe"), "Buscar")

    # --- reportes.ejecutar: un reporte que falla no frena a los demas ---

    def _ok(self, nombre):
        def reporte(page, fecha, carpeta):
            self.assertTrue(page.get_by_text("GESTORES", exact=True).count())  # pagina logueada
            archivo = carpeta / f"{nombre}.xls"
            archivo.write_text("datos", encoding="utf-8")
            return archivo, 1
        return reporte

    def test_ejecutar_sigue_en_la_misma_sesion_despues_de_un_error(self):
        def falla(page, fecha, carpeta):
            raise traxion.BotError("'Desde fecha' quedo en '16/10/2026' en vez de '15/10/2026'")

        def bug(page, fecha, carpeta):
            raise ValueError("algo inesperado")

        self.sesion.iniciar()
        carpeta = Path(self.tmp.name)
        res = reportes.ejecutar(self.sesion, date(2026, 10, 15), carpeta,
                                [("A", self._ok("a")), ("B", falla), ("C", bug), ("D", self._ok("d"))])
        self.assertEqual([(r.nombre, r.archivo and r.archivo.name, r.error) for r in res], [
            ("A", "a.xls", None),
            ("B", None, "'Desde fecha' quedo en '16/10/2026' en vez de '15/10/2026'"),
            ("C", None, "algo inesperado"),
            ("D", "d.xls", None),
        ])
        # la pagina seguia usable: un solo login en toda la corrida (Traxion no deja dos sesiones)
        self.assertEqual(self.traxion.pedidos.count("/login"), 1)
        self.assertEqual(self.traxion.pedidos.count("/salir/si"), 0)
        self.assertIn("Traceback", self.leer_log())  # el error inesperado deja el detalle en el log

    def test_ejecutar_vuelve_a_entrar_solo_si_la_sesion_se_perdio(self):
        def vence(page, fecha, carpeta):
            traxion.click_y_esperar(page, page.locator("#vencida"), "Buscar")  # -> SesionVencida

        self.sesion.iniciar()
        res = reportes.ejecutar(self.sesion, date(2026, 10, 15), Path(self.tmp.name),
                                [("A", vence), ("B", self._ok("b"))])
        self.assertEqual([(r.nombre, r.error is None) for r in res], [("A", False), ("B", True)])
        self.assertIn("la sesion vencio", res[0].error)
        self.assertEqual(self.traxion.pedidos.count("/login"), 2)

    def test_ejecutar_si_no_puede_volver_a_entrar_marca_los_que_faltan(self):
        def rompe_y_cambia_la_clave(page, fecha, carpeta):
            config.TRAXION_PASS = "vencida"  # el mock.patch.multiple del setUp la restaura
            traxion.click_y_esperar(page, page.locator("#vencida"), "Buscar")  # -> SesionVencida

        self.sesion.iniciar()
        res = reportes.ejecutar(self.sesion, date(2026, 10, 15), Path(self.tmp.name),
                                [("A", rompe_y_cambia_la_clave), ("B", self._ok("b")), ("C", self._ok("c"))])
        self.assertIn("la sesion vencio", res[0].error)
        for r in res[1:]:
            self.assertIsNone(r.archivo)
            self.assertIn("no se pudo volver a iniciar sesion (Login fallido", r.error)
        self.assertEqual([r.nombre for r in res], ["A", "B", "C"])

    # --- Los tres reportes contra las pantallas de mentira ---

    def assert_nada_peligroso(self):
        peligrosos = [p for p in self.traxion.pedidos if p.startswith("/peligro")]
        self.assertEqual(peligrosos, [], "se clickeo una accion peligrosa de 'Funciones'")

    def test_cuentas(self):
        self.sesion.iniciar()
        archivo, registros = reportes.cuentas(self.sesion.page, date(2026, 10, 14), Path(self.tmp.name))
        self.assertEqual((archivo.name, registros), ("Cuentas_2026-10-14.csv", 258))
        self.assertIn("/cuentas", self.traxion.pedidos)  # el de GESTORES, no el de PROVEEDORES
        self.assertNotIn("/proveedores/cuentas", self.traxion.pedidos)
        form = self.traxion.busquedas["cuentas"]
        # Cta.Cte. ya venia marcado: no se tiene que haber desmarcado
        for texto in ("Cta.Cte.", "Saldo Disponible", "Saldo Virtual"):
            self.assertEqual(form.get(f"mostrar_{texto}"), "on", texto)
        self.assertNotIn("mostrar_Arbol", form)
        self.assertEqual(self.traxion.exportes, ["cuentas"])
        self.assert_nada_peligroso()

    def test_depositos_por_filtros_con_la_fecha_del_reporte(self):
        self.sesion.iniciar()
        archivo, registros = reportes.depositos(self.sesion.page, date(2026, 10, 14), Path(self.tmp.name))
        self.assertEqual((archivo.name, registros), ("Depositos_2026-10-14.csv", 0))  # sin movimientos no es error
        form = self.traxion.busquedas["depositos"]
        self.assertEqual((form["desde_fecha"], form["hasta_fecha"]), ("14/10/2026", "14/10/2026"))
        self.assertEqual((form["desde_hora"], form["hasta_hora"]), ("0:00:00", "23:59:59"))
        for texto in ("PEI", "T.Credito", "Rec.Terceros", "Efectivo", "Depositos", "Cheques"):
            self.assertEqual(form.get(f"incluir_{texto}"), "on", texto)
        self.assertEqual((form.get("dep_Enviados"), form.get("dep_Recibidos")), ("on", "on"))
        self.assertEqual(self.traxion.exportes, ["depositos"])
        self.assert_nada_peligroso()

    def test_ventas_guarda_el_archivo_tal_cual(self):
        self.sesion.iniciar()
        archivo, registros = reportes.ventas(self.sesion.page, date(2026, 10, 15), Path(self.tmp.name))
        self.assertEqual((archivo.name, registros), ("Ventas_2026-10-15.csv", 3))
        self.assertEqual(self.traxion.busquedas["ventas"]["desde_fecha"], "15/10/2026")
        self.assertEqual(archivo.read_bytes(), fake_traxion.EXPORTES["ventas"][1].encode("iso-8859-1"))

    def test_exporte_que_devuelve_html_es_error(self):
        self.traxion.exporte_roto = "ventas"
        self.sesion.iniciar()
        with self.assertRaisesRegex(traxion.BotError, "pagina HTML"):
            reportes.ventas(self.sesion.page, date(2026, 10, 15), Path(self.tmp.name))

    def test_corrida_completa(self):
        self.sesion.iniciar()
        res = reportes.ejecutar(self.sesion, date(2026, 10, 15), Path(self.tmp.name))
        self.assertEqual([(r.nombre, r.error, r.registros) for r in res],
                         [("Depósitos", None, 0), ("Cuentas", None, 258), ("Ventas", None, 3)])
        self.assertEqual(self.traxion.pedidos.count("/login"), 1)  # sin errores no hay relogin
        self.assert_nada_peligroso()

    def test_el_log_no_guarda_la_sesion(self):
        self.sesion.iniciar()
        traxion.log(f"url actual: {self.sesion.page.url}?_s=SECRETO123&_k=CONT456")
        log = self.leer_log()
        self.assertNotIn("SECRETO123", log)
        self.assertNotIn("CONT456", log)


if __name__ == "__main__":
    unittest.main()
