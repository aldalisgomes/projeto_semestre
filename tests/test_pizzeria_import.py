import csv
import io
import unittest

import pandas as pd

from src.pizzeria_import import (
    DAY_NAMES,
    parse_sales_csv,
    schedule_from_rows,
    suggest_column_mapping,
    validate_sales_csv,
)


HEADERS = [
    "data",
    "quantidade",
    "pedido_id",
    "hora",
    "produto",
    "tamanho",
    "preco_unitario",
    "categoria",
    "ingredientes",
]


def csv_bytes(rows, headers=HEADERS):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def default_schedule(closed=()):
    return {
        day: {
            "is_open": day not in closed,
            "opens_at": "00:00",
            "closes_at": "23:59",
        }
        for day in range(7)
    }


def validate(data, *, headers=HEADERS, closed=(), schedule_confirmed=True, confirm_open=True, identity="global", schedule=None):
    parsed = parse_sales_csv(data if isinstance(data, bytes) else data.encode("utf-8"))
    suggested, _ = suggest_column_mapping(parsed.headers)
    return validate_sales_csv(
        parsed,
        suggested,
        order_identity=identity,
        schedule=schedule if schedule is not None else default_schedule(closed),
        schedule_confirmed=schedule_confirmed,
        confirm_open_no_sales=confirm_open,
    )


def row(date="2026-01-15", qty="1", order="001", hour="18:30", product="Calabresa", size="M", price="35.90", category="Tradicional", ingredients="Molho; queijo"):
    return [date, qty, order, hour, product, size, price, category, ingredients]


class PizzeriaImportTests(unittest.TestCase):
    def test_01_standard_csv_maps_and_validates(self):
        result = validate(csv_bytes([row()]))
        self.assertTrue(result.mapping_ready)
        self.assertEqual(result.summary["valid_analysis_rows"], 1)

    def test_02_multi_line_order_is_one_order_and_not_duplicate(self):
        result = validate(csv_bytes([row(qty="2", product="Calabresa"), row(qty="1", product="Margherita", price="32.00")]))
        self.assertEqual(result.summary["distinct_orders"], 1)
        self.assertEqual(result.summary["units"], 3)
        self.assertEqual(result.summary["duplicate_affected_rows"], 0)

    def test_03_identical_products_in_different_orders_are_not_duplicate(self):
        result = validate(csv_bytes([row(order="001"), row(order="002")]))
        self.assertEqual(result.summary["distinct_orders"], 2)
        self.assertEqual(result.summary["duplicate_affected_rows"], 0)

    def test_04_exact_repeat_warns_but_preserves_both_rows(self):
        result = validate(csv_bytes([row(), row()]))
        self.assertEqual(result.summary["duplicate_groups"], 1)
        self.assertEqual(result.summary["duplicate_affected_rows"], 2)
        self.assertEqual(len(result.analysis_frame), 2)
        self.assertIn("nenhuma linha será excluída", " ".join(result.issues["Mensagem"].astype(str)))

    def test_05_cross_date_order_identity_config(self):
        data = csv_bytes([row(date="2026-01-15"), row(date="2026-01-16")])
        global_result = validate(data, identity="global")
        daily_result = validate(data, identity="date_order")
        self.assertEqual(global_result.summary["distinct_orders"], 1)
        self.assertEqual(daily_result.summary["distinct_orders"], 2)
        self.assertEqual(global_result.summary["cross_date_order_ids"], 1)

    def test_06_missing_order_id_keeps_units_but_not_order_count(self):
        result = validate(csv_bytes([row(order=""), row(order="001")]))
        self.assertEqual(result.summary["units"], 2)
        self.assertEqual(result.summary["distinct_orders"], 1)
        self.assertEqual(result.summary["missing_order_id_rows"], 1)
        self.assertTrue((result.issues["Coluna"] == "pedido_id").any())

    def test_07_invalid_price_disables_complete_revenue(self):
        result = validate(csv_bytes([row(price="R$ 35,90")]))
        self.assertFalse(result.revenue_available)
        self.assertEqual(result.summary["invalid_price_rows"], 1)

    def test_08_negative_quantity_is_an_error_and_not_an_analysis_row(self):
        result = validate(csv_bytes([row(qty="-2")]))
        self.assertEqual(result.summary["invalid_quantity_rows"], 1)
        self.assertEqual(len(result.analysis_frame), 0)

    def test_09_decimal_quantity_is_rejected(self):
        result = validate(csv_bytes([row(qty="1.5")]))
        self.assertEqual(result.summary["invalid_quantity_rows"], 1)

    def test_10_impossible_date_is_reported(self):
        result = validate(csv_bytes([row(date="2026-02-30")]))
        self.assertEqual(result.summary["invalid_date_rows"], 1)

    def test_11_invalid_time_is_reported_without_dropping_sale(self):
        result = validate(csv_bytes([row(hour="27:80")]))
        self.assertEqual(result.summary["valid_analysis_rows"], 1)
        self.assertTrue(((result.issues["Coluna"] == "hora") & (result.issues["Tipo"] == "Erro")).any())

    def test_12_required_column_absence_blocks_mapping(self):
        data = csv_bytes([["001", "18:30"]], headers=["pedido_id", "hora"])
        result = validate(data, headers=["pedido_id", "hora"])
        self.assertFalse(result.mapping_ready)

    def test_13_missing_ingredients_only_disables_that_analysis(self):
        headers = [name for name in HEADERS if name != "ingredientes"]
        result = validate(csv_bytes([row()[:-1]], headers=headers), headers=headers)
        self.assertTrue(result.mapping_ready)
        self.assertTrue(any("ingredientes" in str(value) for value in result.issues["Coluna"]))

    def test_14_missing_category_is_reported_as_optional_capability(self):
        headers = [name for name in HEADERS if name != "categoria"]
        values = row()[:7] + [row()[-1]]
        result = validate(csv_bytes([values], headers=headers), headers=headers)
        self.assertTrue(result.mapping_ready)
        self.assertTrue(any(result.issues["Coluna"] == "categoria"))

    def test_15_unusual_sizes_are_preserved_without_fixed_allowlist(self):
        result = validate(csv_bytes([row(size="XXL")]))
        self.assertIn("XXL", result.summary["sizes"])

    def test_16_equivalent_headers_are_suggested_but_not_applied_without_confirmation(self):
        headers = ["data_venda", "quantidade", "id_pedido", "horario", "produto_nome", "tamanho", "preco", "categoria", "ingredientes"]
        data = csv_bytes([row()], headers=headers)
        parsed = parse_sales_csv(data)
        suggestions, _ = suggest_column_mapping(parsed.headers)
        self.assertEqual(suggestions["data"], "data_venda")
        self.assertEqual(suggestions["pedido_id"], "id_pedido")
        self.assertEqual(suggestions["produto"], "produto_nome")

    def test_17_all_days_open_is_supported(self):
        result = validate(csv_bytes([row()]), schedule=default_schedule())
        self.assertEqual(result.closed_weekdays, ())

    def test_18_arbitrary_closed_weekday_is_supported(self):
        wednesday = 2
        result = validate(csv_bytes([row()]), closed=(wednesday,))
        self.assertIn(wednesday, result.closed_weekdays)

    def test_19_open_day_without_record_is_unknown_until_confirmed(self):
        data = csv_bytes([row(date="2026-01-15"), row(date="2026-01-17")])
        unknown = validate(data, confirm_open=False)
        confirmed = validate(data, confirm_open=True)
        self.assertIn(pd.Timestamp("2026-01-16"), unknown.unknown_dates)
        self.assertNotIn(pd.Timestamp("2026-01-16"), confirmed.unknown_dates)
        self.assertIn(pd.Timestamp("2026-01-16"), confirmed.summary["confirmed_zero_dates"])
        self.assertFalse(unknown.forecast_ready)

    def test_20_closed_day_without_record_is_zero_in_time_series(self):
        data = csv_bytes([row(date="2026-01-15"), row(date="2026-01-17")])
        result = validate(data, closed=(4,), confirm_open=False)  # Friday is weekday 4.
        self.assertNotIn(pd.Timestamp("2026-01-16"), result.unknown_dates)
        self.assertIn(pd.Timestamp("2026-01-16"), result.summary["confirmed_zero_dates"])
        self.assertIn(4, result.closed_weekdays)

    def test_21_brazilian_date_is_recognized_when_column_order_is_unambiguous(self):
        data = csv_bytes([row(date="22/08/2026"), row(date="30/09/2026")])
        result = validate(data)
        self.assertEqual(result.summary["invalid_date_rows"], 0)
        self.assertEqual(result.summary["date_start"], pd.Timestamp("2026-08-22"))

    def test_21a_iso_and_brazilian_dates_are_normalized_and_analyzed_together(self):
        data = csv_bytes([
            row(date="2026-08-12", qty="2", order="001"),
            row(date="13/08/2026", qty="3", order="002"),
            row(date="14/08/2026", qty="1", order="003"),
        ])
        result = validate(data)
        self.assertEqual(result.summary["invalid_date_rows"], 0)
        self.assertEqual(result.summary["units"], 6)
        self.assertEqual(result.summary["distinct_orders"], 3)
        self.assertEqual(
            result.analysis_frame["data"].tolist(),
            [pd.Timestamp("2026-08-12"), pd.Timestamp("2026-08-13"), pd.Timestamp("2026-08-14")],
        )
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(result.analysis_frame["data"]))

    def test_21b_single_unambiguous_brazilian_date_is_accepted_and_original_is_preserved(self):
        original = csv_bytes([row(date="13/08/2026")])
        parsed = parse_sales_csv(original)
        mapping, _ = suggest_column_mapping(parsed.headers)
        result = validate_sales_csv(parsed, mapping, schedule=default_schedule(), schedule_confirmed=True, confirm_open_no_sales=True)
        self.assertEqual(result.summary["invalid_date_rows"], 0)
        self.assertEqual(result.analysis_frame.iloc[0]["data"], pd.Timestamp("2026-08-13"))
        self.assertEqual(parsed.frame.iloc[0]["data"], "13/08/2026")

    def test_21c_impossible_incomplete_and_ambiguous_dates_report_original_csv_lines(self):
        data = csv_bytes([
            row(date="2026-02-30"),
            row(date="31/02/2026"),
            row(date="13/08/26"),
            row(date="01/02/2026"),
        ])
        result = validate(data)
        date_issues = result.issues.loc[result.issues["Coluna"].eq("data")]
        self.assertEqual(result.summary["invalid_date_rows"], 4)
        self.assertEqual(set(date_issues["Número da linha original"].astype(str)), {"2", "3", "4", "5"})
        self.assertEqual(len(result.analysis_frame), 0)

    def test_22_ambiguous_date_is_not_silently_interpreted(self):
        result = validate(csv_bytes([row(date="01/02/2026")]))
        self.assertEqual(result.summary["invalid_date_rows"], 1)
        self.assertTrue(any("ambígua" in str(value).lower() for value in result.issues["Mensagem"]))
        date_issue = result.issues.loc[result.issues["Coluna"].eq("data")].iloc[0]
        self.assertEqual(str(date_issue["Número da linha original"]), "2")

    def test_23_price_comma_decimal_is_accepted_but_thousands_ambiguous_is_not(self):
        accepted = validate(csv_bytes([row(price="35,90")]))
        rejected = validate(csv_bytes([row(price="1,234")]))
        self.assertTrue(accepted.revenue_available)
        self.assertFalse(rejected.revenue_available)

    def test_24_leading_zero_order_ids_are_preserved_as_text(self):
        parsed = parse_sales_csv(csv_bytes([row(order="00001")]))
        self.assertEqual(parsed.frame.iloc[0]["pedido_id"], "00001")

    def test_25_open_hours_outside_configured_window_are_warned(self):
        schedule = default_schedule()
        schedule[3]["opens_at"] = "19:00"
        result = validate(csv_bytes([row(hour="18:30")]), schedule=schedule)
        self.assertTrue(any("fora do funcionamento" in str(value) for value in result.issues["Mensagem"]))

    def test_26_same_order_with_different_products_is_not_duplicate(self):
        result = validate(csv_bytes([row(product="Calabresa"), row(product="Margherita")]))
        self.assertEqual(result.summary["duplicate_groups"], 0)
        self.assertEqual(result.summary["distinct_orders"], 1)

    def test_27_header_spacing_case_and_semicolon_delimiter_are_supported(self):
        text = " Data Venda ; Qtd ; ID Pedido ; Produto Nome \n2026-01-15;1;001;Calabresa\n"
        parsed = parse_sales_csv(text.encode("utf-8"))
        suggestions, _ = suggest_column_mapping(parsed.headers)
        self.assertEqual(parsed.delimiter, ";")
        self.assertEqual(suggestions["data"], " Data Venda ")
        self.assertEqual(suggestions["quantidade"], " Qtd ")

    def test_28_inconsistent_field_count_is_reported_and_original_rows_remain(self):
        parsed = parse_sales_csv(b"data,quantidade\n2026-01-15,1\n2026-01-16,2,extra\n")
        self.assertEqual(len(parsed.frame), 2)
        self.assertTrue(parsed.frame["__malformed__"].iloc[1])
        self.assertTrue(any(issue["Coluna"] == "estrutura" for issue in parsed.issues))

    def test_29_schedule_from_ui_rows_keeps_day_specific_hours(self):
        rows = [
            {"Dia": DAY_NAMES[0], "Abre?": False, "Abertura": "", "Fechamento": ""},
            {"Dia": DAY_NAMES[1], "Abre?": True, "Abertura": "17:00", "Fechamento": "22:00"},
        ]
        result = schedule_from_rows(rows)
        self.assertFalse(result[0]["is_open"])
        self.assertEqual(result[1]["opens_at"], "17:00")

    def test_30_sixty_day_history_can_enable_forecast_when_calendar_is_complete(self):
        rows = [row(date=(pd.Timestamp("2026-01-01") + pd.Timedelta(days=day)).strftime("%Y-%m-%d"), order=f"{day:03d}") for day in range(60)]
        result = validate(csv_bytes(rows), confirm_open=False)
        self.assertTrue(result.forecast_ready)


if __name__ == "__main__":
    unittest.main()
