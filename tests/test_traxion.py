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
            return archivo
        return reporte

    def test_ejecutar_sigue_despues_de_un_error_y_vuelve_a_entrar(self):
        def rompe(page, fecha, carpeta):
            raise traxion.SinRespuesta("Buscar: la plataforma no respondio en 180 s")

        def bug(page, fecha, carpeta):
            raise ValueError("algo inesperado")

        self.sesion.iniciar()
        carpeta = Path(self.tmp.name)
        res = reportes.ejecutar(self.sesion, date(2026, 10, 15), carpeta,
                                [("A", self._ok("a")), ("B", rompe), ("C", bug), ("D", self._ok("d"))])
        self.assertEqual([(r.nombre, r.archivo and r.archivo.name, r.error) for r in res], [
            ("A", "a.xls", None),
            ("B", None, "Buscar: la plataforma no respondio en 180 s"),
            ("C", None, "algo inesperado"),
            ("D", "d.xls", None),
        ])
        # despues de cada error se cerro sesion y se volvio a entrar
        self.assertEqual(self.traxion.pedidos.count("/login"), 3)
        self.assertEqual(self.traxion.pedidos.count("/salir/si"), 2)
        self.assertIn("Traceback", self.leer_log())  # el error inesperado deja el detalle en el log

    def test_ejecutar_si_no_puede_volver_a_entrar_marca_los_que_faltan(self):
        def rompe_y_cambia_la_clave(page, fecha, carpeta):
            config.TRAXION_PASS = "vencida"  # el mock.patch.multiple del setUp la restaura
            raise traxion.BotError("fallo")

        self.sesion.iniciar()
        res = reportes.ejecutar(self.sesion, date(2026, 10, 15), Path(self.tmp.name),
                                [("A", rompe_y_cambia_la_clave), ("B", self._ok("b")), ("C", self._ok("c"))])
        self.assertEqual(res[0].error, "fallo")
        for r in res[1:]:
            self.assertIsNone(r.archivo)
            self.assertIn("no se pudo volver a iniciar sesion (Login fallido", r.error)
        self.assertEqual([r.nombre for r in res], ["A", "B", "C"])

    def test_el_log_no_guarda_la_sesion(self):
        self.sesion.iniciar()
        traxion.log(f"url actual: {self.sesion.page.url}?_s=SECRETO123&_k=CONT456")
        log = self.leer_log()
        self.assertNotIn("SECRETO123", log)
        self.assertNotIn("CONT456", log)


if __name__ == "__main__":
    unittest.main()
