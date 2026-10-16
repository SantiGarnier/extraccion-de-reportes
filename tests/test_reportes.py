"""Pruebas de la fecha del reporte, la retencion de carpetas y el mail (sin navegador ni red)."""
import smtplib
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

import config
import correo
import reportes
from reportes import Resultado
from traxion import BotError


class TestFechaDelReporte(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(config, "HORA_CORTE_FECHA", 6)
        p.start()
        self.addCleanup(p.stop)

    def test_cron_pasada_la_medianoche_saca_el_dia_anterior(self):
        self.assertEqual(reportes.fecha_del_reporte(datetime(2026, 10, 16, 0, 10)), date(2026, 10, 15))
        self.assertEqual(reportes.fecha_del_reporte(datetime(2026, 10, 16, 0, 0)), date(2026, 10, 15))
        self.assertEqual(reportes.fecha_del_reporte(datetime(2026, 10, 16, 5, 59)), date(2026, 10, 15))

    def test_a_mano_a_la_noche_es_hoy(self):
        self.assertEqual(reportes.fecha_del_reporte(datetime(2026, 10, 15, 23, 59)), date(2026, 10, 15))

    def test_de_dia_es_hoy(self):
        self.assertEqual(reportes.fecha_del_reporte(datetime(2026, 10, 16, 6, 0)), date(2026, 10, 16))

    def test_cambio_de_mes_y_anio(self):
        self.assertEqual(reportes.fecha_del_reporte(datetime(2027, 1, 1, 0, 1)), date(2026, 12, 31))


class TestLimpiarReportes(unittest.TestCase):
    def test_borra_solo_carpetas_de_fecha_vencidas(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for nombre in ("2026-09-01", "2026-10-01", "2026-10-15", "otra-cosa"):
                (base / nombre).mkdir()
            with mock.patch.multiple(config, REPORTES_DIR=base, REPORTES_RETENCION_DIAS=30,
                                     LOG_DIR=base / "logs"):
                reportes.limpiar_reportes(hoy=date(2026, 10, 15))
            quedan = sorted(p.name for p in base.iterdir() if p.name != "logs")
            self.assertEqual(quedan, ["2026-10-01", "2026-10-15", "otra-cosa"])


class TestCorreo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.multiple(
            config, SMTP_HOST="smtp.ethereal.email", SMTP_PORT=587, SMTP_USER="u", SMTP_PASS="p",
            SMTP_FROM="Pago24 Red <noreply@pago24.com.ar>", SMTP_SECURE=False,
            SMTP_TO=["uno@ejemplo.com", "otro@ejemplo.com"],
            MAIL_ASUNTO="Reportes Traxion", LOG_DIR=Path(self.tmp.name) / "logs")
        p.start()
        self.addCleanup(p.stop)
        self.inicio = datetime(2026, 10, 15, 23, 59)
        self.fin = datetime(2026, 10, 16, 0, 4)

    def archivo(self, nombre: str) -> Path:
        a = Path(self.tmp.name) / nombre
        a.write_bytes(b"x" * 2048)
        return a

    def test_todo_ok(self):
        res = [Resultado("Depositos", archivo=self.archivo("dep.xls")),
               Resultado("Ventas", archivo=self.archivo("ventas.csv"))]
        msg = correo.armar(date(2026, 10, 15), res, self.inicio, self.fin)
        self.assertEqual(msg["Subject"], "Reportes Traxion 15/10/2026")
        self.assertEqual(msg["To"], "uno@ejemplo.com, otro@ejemplo.com")
        self.assertEqual([a.get_filename() for a in msg.iter_attachments()], ["dep.xls", "ventas.csv"])
        cuerpo = msg.get_body().get_content()
        self.assertIn("corrida del 15/10 23:59 al 16/10 00:04", cuerpo)
        self.assertIn("Depositos: dep.xls (2 KB)", cuerpo)
        self.assertNotIn("No se pudieron", cuerpo)

    def test_cantidad_de_registros(self):
        res = [Resultado("Depósitos", archivo=self.archivo("dep.csv"), registros=0),
               Resultado("Cuentas", archivo=self.archivo("cue.csv"), registros=1258),
               Resultado("Ventas", archivo=self.archivo("ven.csv"), registros=1)]
        cuerpo = correo.armar(date(2026, 10, 15), res, self.inicio, self.fin).get_body().get_content()
        self.assertIn("Depósitos: dep.csv (2 KB, sin movimientos)", cuerpo)
        self.assertIn("Cuentas: cue.csv (2 KB, 1.258 registros)", cuerpo)
        self.assertIn("Ventas: ven.csv (2 KB, 1 registro)", cuerpo)

    def test_archivo_chico_en_bytes(self):
        a = Path(self.tmp.name) / "chico.csv"
        a.write_bytes(b"x" * 25)
        msg = correo.armar(date(2026, 10, 15), [Resultado("Prueba", archivo=a)], self.inicio, self.fin)
        self.assertIn("Prueba: chico.csv (25 bytes)", msg.get_body().get_content())

    def test_con_errores_manda_lo_hecho_y_el_motivo_de_lo_que_fallo(self):
        res = [Resultado("Depositos", archivo=self.archivo("dep.xls")),
               Resultado("Cuentas", error="Buscar: la plataforma no respondio en 180 s")]
        msg = correo.armar(date(2026, 10, 15), res, self.inicio, self.fin)
        self.assertEqual(msg["Subject"], "Reportes Traxion 15/10/2026 - CON ERRORES")
        self.assertEqual([a.get_filename() for a in msg.iter_attachments()], ["dep.xls"])
        cuerpo = msg.get_body().get_content()
        self.assertIn("Cuentas: Buscar: la plataforma no respondio en 180 s", cuerpo)

    def test_enviar_usa_starttls_antes_del_login(self):
        msg = correo.armar(date(2026, 10, 15), [], self.inicio, self.fin)
        with mock.patch("smtplib.SMTP") as smtp:
            correo.enviar(msg)
        s = smtp.return_value.__enter__.return_value
        smtp.assert_called_once_with("smtp.ethereal.email", 587, timeout=60)
        llamadas = [c[0] for c in s.method_calls]
        self.assertEqual(llamadas, ["starttls", "login", "send_message"])

    def test_clave_rechazada_explica_que_revisar(self):
        msg = correo.armar(date(2026, 10, 15), [], self.inicio, self.fin)
        with mock.patch("smtplib.SMTP") as smtp:
            smtp.return_value.__enter__.return_value.login.side_effect = smtplib.SMTPAuthenticationError(
                535, b"Authentication failed")
            with self.assertRaisesRegex(BotError, r"rechazo SMTP_USER/SMTP_PASS \(535\)"):
                correo.enviar(msg)

    def test_enviar_sin_destinatarios_no_intenta(self):
        msg = correo.armar(date(2026, 10, 15), [], self.inicio, self.fin)
        with mock.patch.object(config, "SMTP_TO", []), mock.patch("smtplib.SMTP") as smtp:
            with self.assertRaisesRegex(BotError, "SMTP_TO"):
                correo.enviar(msg)
        smtp.assert_not_called()


class TestDestinatarios(unittest.TestCase):
    def test_smtp_to_separado_por_coma(self):
        import importlib
        with mock.patch.dict("os.environ", {"SMTP_TO": " a@x.com, b@y.com ,,c@z.com "}):
            recargado = importlib.reload(config)
            self.assertEqual(recargado.SMTP_TO, ["a@x.com", "b@y.com", "c@z.com"])
        importlib.reload(config)


if __name__ == "__main__":
    unittest.main()
