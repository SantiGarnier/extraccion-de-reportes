"""Pruebas de main.py: aunque el bot se caiga por algo inesperado, el mail sale igual (sin navegador ni red)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from playwright.sync_api import Error as PWError

import config
import main
from reportes import Resultado


class TestBotQueSeCae(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        p = mock.patch.multiple(config, LOG_DIR=base / "logs", DEBUG_DIR=base / "debug", REPORTES_DIR=base / "reportes",
                                SMTP_FROM="bot@ejemplo.com", SMTP_TO=["uno@ejemplo.com"], MAIL_ASUNTO="Reportes Traxion")
        p.start()
        self.addCleanup(p.stop)
        enviar = mock.patch("correo.enviar")
        self.enviar = enviar.start()
        self.addCleanup(enviar.stop)

    def correr_main(self, *argumentos: str) -> int:
        with mock.patch("sys.argv", ["main.py", "--fecha", "2026-10-28", *argumentos]):
            return main.main()

    def mail(self):
        self.enviar.assert_called_once()
        msg = self.enviar.call_args.args[0]
        return msg["Subject"], msg.get_body().get_content()

    def test_chromium_no_arranca_y_el_mail_sale_igual(self):
        error = PWError("BrowserType.launch: Executable doesn't exist at /root/.cache/ms-playwright/chromium")
        with mock.patch("main.sync_playwright", side_effect=error):
            self.assertEqual(self.correr_main(), 1)
        asunto, cuerpo = self.mail()
        self.assertEqual(asunto, "Reportes Traxion 28/10/2026 - CON ERRORES")
        for nombre in ("Depósitos", "Cuentas", "Ventas"):
            self.assertIn(f"{nombre}: el bot fallo antes de terminar (BrowserType.launch: Executable doesn't exist",
                          cuerpo)
        log = "".join(p.read_text(encoding="utf-8") for p in config.LOG_DIR.glob("*.log"))
        self.assertIn("Traceback", log)  # el detalle completo queda en el log

    def test_con_sin_mail_no_manda_nada(self):
        with mock.patch("main.sync_playwright", side_effect=RuntimeError("se rompio")):
            self.assertEqual(self.correr_main("--sin-mail"), 1)
        self.enviar.assert_not_called()

    def test_error_al_cerrar_el_navegador_no_pierde_los_reportes(self):
        archivo = config.REPORTES_DIR / "Ventas_2026-10-28.csv"
        archivo.parent.mkdir(parents=True)
        archivo.write_text("Nro.Ope.;Fecha\n", encoding="utf-8")
        ok = [Resultado("Ventas", archivo=archivo, registros=0)]
        pw = mock.MagicMock()
        pw.__enter__.return_value.chromium.launch.return_value.new_context.return_value.close.side_effect = \
            PWError("Target page, context or browser has been closed")
        with mock.patch("main.sync_playwright", return_value=pw), mock.patch("main.Sesion"), \
                mock.patch("reportes.ejecutar", return_value=ok):
            self.assertEqual(self.correr_main(), 0)
        asunto, cuerpo = self.mail()
        self.assertEqual(asunto, "Reportes Traxion 28/10/2026")
        self.assertIn("Ventas: Ventas_2026-10-28.csv", cuerpo)


if __name__ == "__main__":
    unittest.main()
