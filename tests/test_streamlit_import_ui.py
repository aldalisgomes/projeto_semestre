import csv
import io
import unittest
import warnings
from pathlib import Path

from streamlit.testing.v1 import AppTest


class StreamlitImportUiTests(unittest.TestCase):
    def test_external_import_keeps_duplicate_rows_and_public_sources_are_independent(self):
        warnings.filterwarnings("ignore")
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(
            ["data", "quantidade", "pedido_id", "hora", "produto", "tamanho", "preco_unitario", "categoria", "ingredientes"]
        )
        record = ["2026-01-15", "2", "0001", "18:30", "Calabresa", "M", "35.90", "Tradicional", "Molho; queijo"]
        writer.writerow(record)
        writer.writerow(record)
        file_bytes = buffer.getvalue().encode("utf-8")

        dashboard_path = Path(__file__).resolve().parents[1] / "src" / "03_streamlit_dashboard.py"
        app = AppTest.from_file(str(dashboard_path), default_timeout=120).run()
        self.assertFalse(app.exception, [error.message for error in app.exception])
        self.assertEqual({metric.label: metric.value for metric in app.metric}["Pizzas vendidas"], "49.574")

        source_radio = next(widget for widget in app.radio if widget.label == "Fonte dos dados")
        source_radio.set_value("Carregar CSV de outra pizzaria").run()
        app.get("file_uploader")[0].set_value(("teste_sintetico.csv", file_bytes, "text/csv")).run()
        self.assertFalse(app.exception, [error.message for error in app.exception])
        self.assertTrue(any("possíveis duplicidades" in str(warning.value).lower() for warning in app.warning))
        buttons = [button.label for button in app.get("download_button")]
        self.assertIn("Baixar relatório de validação", buttons)
        self.assertIn("Baixar CSV original sem alterações", buttons)

        self._confirm(app, "Revisei e confirmo o mapeamento")
        self._confirm(app, "Revisei e confirmo os dias e horários")
        self._confirm(app, "Revisei o diagnóstico e confirmo a análise")
        self.assertFalse(app.exception, [error.message for error in app.exception])
        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Pedidos"], "1")
        self.assertEqual(metrics["Pizzas vendidas"], "4")
        self.assertEqual(metrics["Receita bruta"], "R$ 143,60")
        self.assertEqual(metrics["Valor médio por pedido"], "R$ 143,60")
        self.assertEqual(metrics["Pizzas por pedido"], "4,00")

        source_radio = next(widget for widget in app.radio if widget.label == "Fonte dos dados")
        source_radio.set_value("Base pública original do projeto").run()
        self.assertFalse(app.exception, [error.message for error in app.exception])
        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Pedidos"], "21.350")
        self.assertEqual(metrics["Pizzas vendidas"], "49.574")

        source_radio = next(widget for widget in app.radio if widget.label == "Fonte dos dados")
        source_radio.set_value("Estudo de caso — VENDAS_PIZZARIA_BAIRRO").run()
        self.assertFalse(app.exception, [error.message for error in app.exception])
        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Pedidos"], "583")
        self.assertEqual(metrics["Pizzas vendidas"], "845")
        forecast = next(frame.value for frame in app.dataframe if getattr(frame.value, "shape", None) == (7, 7))
        monday = forecast.loc[forecast["Dia"] == "segunda-feira"]
        self.assertEqual(len(forecast), 7)
        self.assertEqual(forecast["Data"].iloc[0], "01/10/2026")
        self.assertEqual(forecast["Data"].iloc[-1], "07/10/2026")
        self.assertEqual(len(monday), 1)
        self.assertEqual(int(monday.iloc[0]["Previsão de pizzas"]), 0)
        self.assertTrue((forecast["Previsão de pizzas"] >= 0).all())

    def test_missing_optional_order_and_price_fields_keep_volume_only(self):
        content = (
            "data,quantidade,produto,tamanho\n"
            "2026-01-15,1,Calabresa,XXL\n"
            "2026-01-15,2,Margherita,M\n"
        ).encode("utf-8")
        dashboard_path = Path(__file__).resolve().parents[1] / "src" / "03_streamlit_dashboard.py"
        app = AppTest.from_file(str(dashboard_path), default_timeout=120).run()
        source_radio = next(widget for widget in app.radio if widget.label == "Fonte dos dados")
        source_radio.set_value("Carregar CSV de outra pizzaria").run()
        app.get("file_uploader")[0].set_value(("volume_somente.csv", content, "text/csv")).run()
        self.assertFalse(app.exception, [error.message for error in app.exception])
        self._confirm(app, "Revisei e confirmo o mapeamento")
        self._confirm(app, "Revisei e confirmo os dias e horários")
        self._confirm(app, "Revisei o diagnóstico e confirmo a análise")
        self.assertFalse(app.exception, [error.message for error in app.exception])
        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Pizzas vendidas"], "3")
        self.assertEqual(metrics["Pedidos"], "—")
        self.assertEqual(metrics["Receita bruta"], "—")
        self.assertEqual(metrics["Valor médio por pedido"], "—")
        self.assertEqual(metrics["Pizzas por pedido"], "—")

    def test_iso_and_brazilian_dates_feed_dashboard_indicators(self):
        content = (
            "data,quantidade,pedido_id,preco_unitario\n"
            "2026-08-12,2,001,35.90\n"
            "13/08/2026,3,002,35.90\n"
        ).encode("utf-8")
        dashboard_path = Path(__file__).resolve().parents[1] / "src" / "03_streamlit_dashboard.py"
        app = AppTest.from_file(str(dashboard_path), default_timeout=120).run()
        source_radio = next(widget for widget in app.radio if widget.label == "Fonte dos dados")
        source_radio.set_value("Carregar CSV de outra pizzaria").run()
        app.get("file_uploader")[0].set_value(("datas_mistas.csv", content, "text/csv")).run()
        self.assertFalse(app.exception, [error.message for error in app.exception])
        self._confirm(app, "Revisei e confirmo o mapeamento")
        self._confirm(app, "Revisei e confirmo os dias e horários")
        self._confirm(app, "Revisei o diagnóstico e confirmo a análise")
        self.assertFalse(app.exception, [error.message for error in app.exception])
        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Pedidos"], "2")
        self.assertEqual(metrics["Pizzas vendidas"], "5")
        self.assertEqual(metrics["Receita bruta"], "R$ 179,50")

    @staticmethod
    def _confirm(app, label_fragment):
        matching = [widget for widget in app.checkbox if label_fragment in widget.label]
        if len(matching) != 1:
            raise AssertionError(f"Expected one checkbox matching {label_fragment!r}, found {len(matching)}")
        matching[0].set_value(True).run()


if __name__ == "__main__":
    unittest.main()
