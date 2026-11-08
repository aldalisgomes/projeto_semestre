"""CSV import and validation helpers for external pizzeria sales files.

This module is deliberately separate from the public-dataset ETL and SQL code.
It preserves the uploaded bytes, reports issues without deleting rows, and
returns a normalized view only for analyses that can safely use it.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, time
from difflib import SequenceMatcher
from typing import Any, Mapping

import pandas as pd


CANONICAL_COLUMNS = (
    "data",
    "quantidade",
    "pedido_id",
    "hora",
    "produto",
    "tamanho",
    "preco_unitario",
    "categoria",
    "ingredientes",
)
REQUIRED_COLUMNS = ("data", "quantidade")
RECOMMENDED_COLUMNS = ("pedido_id", "hora", "produto", "tamanho", "preco_unitario", "categoria")
OPTIONAL_COLUMNS = ("ingredientes",)
DAY_NAMES = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")
ALIASES = {
    "data": {"data", "date", "data_venda", "data_pedido", "dt_venda", "sale_date"},
    "quantidade": {"quantidade", "quantity", "qtd", "qtde", "unidades", "unidades_vendidas", "qty"},
    "pedido_id": {"pedido_id", "id_pedido", "order_id", "orderid", "numero_pedido", "pedido"},
    "hora": {"hora", "horario", "time", "hora_pedido", "horario_pedido", "sale_time"},
    "produto": {"produto", "produto_nome", "nome_produto", "product", "product_name", "pizza", "sabor", "nome_pizza"},
    "tamanho": {"tamanho", "tamanho_pizza", "size", "pizza_size"},
    "preco_unitario": {"preco_unitario", "preco", "valor_unitario", "preco_venda", "unit_price", "price"},
    "categoria": {"categoria", "category", "tipo_categoria"},
    "ingredientes": {"ingredientes", "ingredients", "composicao"},
}
ISSUE_COLUMNS = (
    "Número da linha original",
    "Coluna",
    "Valor encontrado",
    "Tipo",
    "Mensagem",
    "Ação recomendada",
)


@dataclass
class CsvReadResult:
    """Parsed CSV view plus structural diagnostics; original bytes stay untouched."""

    frame: pd.DataFrame
    headers: list[str]
    original_headers: list[str]
    delimiter: str
    encoding: str
    issues: list[dict[str, Any]]
    empty: bool = False


@dataclass
class ValidationResult:
    """Validation output and a separate analysis-ready view."""

    analysis_frame: pd.DataFrame
    mapped_frame: pd.DataFrame
    issues: pd.DataFrame
    duplicate_rows: pd.DataFrame
    summary: dict[str, Any]
    unknown_dates: list[pd.Timestamp]
    closed_weekdays: tuple[int, ...]
    revenue_available: bool
    forecast_ready: bool
    mapping_ready: bool
    status: str


def normalize_column_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


_ALIAS_LOOKUP = {
    normalize_column_name(alias): canonical
    for canonical, aliases in ALIASES.items()
    for alias in aliases
}


def _unique_headers(headers: list[str]) -> list[str]:
    """Keep duplicate source headers addressable without altering original bytes."""
    output: list[str] = []
    counts: dict[str, int] = {}
    for position, header in enumerate(headers, start=1):
        name = str(header)
        counts[name] = counts.get(name, 0) + 1
        output.append(name if counts[name] == 1 else f"{name}__col{counts[name]}_{position}")
    return output


def parse_sales_csv(file_bytes: bytes) -> CsvReadResult:
    """Parse a CSV while retaining malformed rows and identifying field-count issues."""
    issues: list[dict[str, Any]] = []
    if not file_bytes:
        return CsvReadResult(pd.DataFrame(), [], [], ",", "utf-8", issues, empty=True)

    decoded: str | None = None
    encoding = "utf-8-sig"
    for candidate in ("utf-8-sig", "cp1252", "latin1"):
        try:
            decoded = file_bytes.decode(candidate)
            encoding = candidate
            break
        except UnicodeDecodeError:
            continue
    if decoded is None or not decoded.strip():
        return CsvReadResult(pd.DataFrame(), [], [], ",", encoding, issues, empty=True)

    sample = decoded[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","

    reader = csv.reader(io.StringIO(decoded, newline=""), delimiter=delimiter, strict=True)
    try:
        raw_headers = next(reader)
    except StopIteration:
        return CsvReadResult(pd.DataFrame(), [], [], delimiter, encoding, issues, empty=True)
    except csv.Error as error:
        issues.append(_issue(1, "cabeçalho", "", "Erro", f"Cabeçalho CSV inválido: {error}", "Confira aspas e separadores e exporte novamente."))
        return CsvReadResult(pd.DataFrame(), [], [], delimiter, encoding, issues, empty=True)

    original_headers = [str(header) for header in raw_headers]
    headers = _unique_headers(original_headers)
    if not any(str(header).strip() for header in original_headers):
        issues.append(_issue(1, "cabeçalho", "", "Erro", "O arquivo não contém nomes de colunas válidos.", "Inclua cabeçalhos na primeira linha do CSV."))
        return CsvReadResult(pd.DataFrame(), headers, original_headers, delimiter, encoding, issues, empty=True)

    normalized_headers = [normalize_column_name(header) for header in original_headers]
    duplicated_headers = {
        normalized for normalized in normalized_headers if normalized and normalized_headers.count(normalized) > 1
    }
    for normalized in sorted(duplicated_headers):
        positions = [str(index + 1) for index, value in enumerate(normalized_headers) if value == normalized]
        issues.append(
            _issue(
                1,
                "cabeçalho",
                normalized,
                "Erro",
                f"Há cabeçalhos repetidos ou equivalentes nas colunas {', '.join(positions)}.",
                "Renomeie as colunas para que cada campo tenha um único cabeçalho.",
            )
        )

    records: list[list[str]] = []
    metadata: list[dict[str, Any]] = []
    previous_line = reader.line_num
    try:
        for record_number, row in enumerate(reader, start=2):
            physical_end_line = reader.line_num
            if not row or (len(row) == 1 and not row[0].strip()):
                previous_line = physical_end_line
                continue
            line_number = previous_line + 1
            previous_line = physical_end_line
            malformed = len(row) != len(headers)
            overflow = ""
            if len(row) > len(headers):
                overflow = " | ".join(row[len(headers):])
                values = row[: len(headers)]
            else:
                values = row + [""] * (len(headers) - len(row))
            records.append([str(value) for value in values])
            metadata.append(
                {
                    "__csv_line__": line_number,
                    "__malformed__": malformed,
                    "__overflow__": overflow,
                    "__record_number__": record_number,
                }
            )
            if malformed:
                found = len(row)
                issues.append(
                    _issue(
                        line_number,
                        "estrutura",
                        " | ".join(str(value) for value in row),
                        "Erro",
                        f"A linha tem {found} campo(s), mas o cabeçalho define {len(headers)} coluna(s).",
                        "Confira separadores e aspas. A linha original não será removida do arquivo enviado.",
                    )
                )
    except csv.Error as error:
        issues.append(
            _issue(
                reader.line_num or 0,
                "estrutura",
                "",
                "Erro",
                f"O CSV contém uma linha que não pôde ser lida: {error}.",
                "Corrija as aspas e os separadores nessa linha e envie novamente.",
            )
        )

    data = pd.DataFrame(records, columns=headers, dtype="string")
    metadata_frame = pd.DataFrame(metadata)
    if not metadata_frame.empty:
        data = pd.concat([data.reset_index(drop=True), metadata_frame], axis=1)
    else:
        data["__csv_line__"] = pd.Series(dtype="int64")
        data["__malformed__"] = pd.Series(dtype="bool")
        data["__overflow__"] = pd.Series(dtype="string")
        data["__record_number__"] = pd.Series(dtype="int64")
    return CsvReadResult(data, headers, original_headers, delimiter, encoding, issues, empty=not records)


def suggest_column_mapping(headers: list[str]) -> tuple[dict[str, str | None], dict[str, list[str]]]:
    """Suggest unique header aliases; ambiguous matches are intentionally left unmapped."""
    suggestions: dict[str, str | None] = {}
    candidates_by_target: dict[str, list[str]] = {}
    for target in CANONICAL_COLUMNS:
        candidates = [header for header in headers if _ALIAS_LOOKUP.get(normalize_column_name(header)) == target]
        candidates_by_target[target] = candidates
        suggestions[target] = candidates[0] if len(candidates) == 1 else None
    return suggestions, candidates_by_target


def _issue(line: Any, column: str, value: Any, kind: str, message: str, action: str) -> dict[str, Any]:
    return {
        "Número da linha original": line if line not in (None, "") else "—",
        "Coluna": column,
        "Valor encontrado": value,
        "Tipo": kind,
        "Mensagem": message,
        "Ação recomendada": action,
    }


def _blank(value: Any) -> bool:
    return value is None or pd.isna(value) or not str(value).strip()


def _infer_slash_date_order(values: list[str]) -> str | None:
    for value in values:
        match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value.strip())
        if not match:
            continue
        day, month = int(match.group(1)), int(match.group(2))
        # A day above 12 identifies DD/MM without guessing. A value in which
        # both components are <= 12 remains ambiguous unless another row in
        # this same file establishes the Brazilian day-first convention.
        if day > 12 and day <= 31 and 1 <= month <= 12:
            parsed = pd.to_datetime(value.strip(), format="%d/%m/%Y", errors="coerce")
            if not pd.isna(parsed):
                return "dmy"
    return None


def _parse_date(value: Any, slash_order: str | None) -> tuple[pd.Timestamp | None, str | None]:
    if _blank(value):
        return None, "data vazia"
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", text):
        parsed = pd.to_datetime(text, format="%Y-%m-%d", errors="coerce")
        return (None, "data impossível") if pd.isna(parsed) else (pd.Timestamp(parsed).normalize(), None)
    if re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", text):
        parsed = pd.to_datetime(text, format="%Y/%m/%d", errors="coerce")
        return (None, "data impossível") if pd.isna(parsed) else (pd.Timestamp(parsed).normalize(), None)
    slash = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if slash:
        day, month = int(slash.group(1)), int(slash.group(2))
        if not (1 <= day <= 31 and 1 <= month <= 12):
            return None, "data impossível ou formato não suportado"
        if day <= 12 and slash_order != "dmy":
            return None, "data ambígua"
        parsed = pd.to_datetime(text, format="%d/%m/%Y", errors="coerce")
        return (None, "data impossível") if pd.isna(parsed) else (pd.Timestamp(parsed).normalize(), None)
    return None, "formato de data não reconhecido"


def parse_sales_dates(values: list[Any]) -> tuple[list[pd.Timestamp | None], list[str | None]]:
    """Parse ISO and Brazilian dates consistently for validation and analysis.

    Ambiguous day/month values are accepted only when another date in the same
    file establishes the DD/MM/YYYY convention. The caller retains the source
    values; this function returns a separate normalized datetime view.
    """
    text_values = ["" if _blank(value) else str(value).strip() for value in values]
    slash_order = _infer_slash_date_order(text_values)
    parsed_dates: list[pd.Timestamp | None] = []
    errors: list[str | None] = []
    for value in text_values:
        parsed_date, error = _parse_date(value, slash_order)
        parsed_dates.append(parsed_date)
        errors.append(error)
    return parsed_dates, errors


def _parse_integer(value: Any) -> tuple[int | None, str | None]:
    if _blank(value):
        return None, "quantidade vazia"
    text = str(value).strip()
    if not re.fullmatch(r"\+?\d+", text):
        return None, "quantidade não é número inteiro"
    number = int(text)
    if number <= 0:
        return None, "quantidade deve ser positiva"
    return number, None


def _parse_price(value: Any) -> tuple[float | None, str | None, bool]:
    """Return numeric price, error, and whether a thousands separator was normalized."""
    if _blank(value):
        return None, "preço vazio", False
    text = str(value).strip().replace(" ", "")
    if re.search(r"R\$|\$|€|£", text, flags=re.IGNORECASE):
        return None, "preço inclui símbolo monetário", False
    if re.fullmatch(r"\+?\d+(?:[.,]\d{1,2})?", text):
        value_number = float(text.replace(",", "."))
        return (value_number, None, False) if value_number > 0 else (None, "preço deve ser positivo", False)
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{1,2}", text):
        value_number = float(text.replace(".", "").replace(",", "."))
        return (value_number, None, True) if value_number > 0 else (None, "preço deve ser positivo", True)
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+\.\d{1,2}", text):
        value_number = float(text.replace(",", ""))
        return (value_number, None, True) if value_number > 0 else (None, "preço deve ser positivo", True)
    if "," in text and "." in text:
        return None, "formato de preço ambíguo", False
    if re.fullmatch(r"\d{1,3}[.,]\d{3}", text):
        return None, "formato de preço ambíguo", False
    return None, "preço não numérico ou com mais de duas casas decimais", False


def _parse_time(value: Any) -> tuple[time | None, str | None]:
    if _blank(value):
        return None, None
    text = str(value).strip()
    if re.fullmatch(r"\d{1,2}", text):
        hour = int(text)
        return (time(hour, 0), None) if 0 <= hour <= 23 else (None, "horário inválido")
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not match:
        return None, "horário fora do padrão HH ou HH:MM"
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None, "horário inválido"
    return time(hour, minute), None


def _time_in_schedule(value: time, opens_at: time, closes_at: time) -> bool:
    if closes_at > opens_at:
        return opens_at <= value < closes_at
    if closes_at < opens_at:  # overnight opening, e.g. 18:00–02:00
        return value >= opens_at or value < closes_at
    return False


def _schedule_entry(schedule: Mapping[Any, Any], weekday: int) -> dict[str, Any] | None:
    entry = schedule.get(weekday)
    if entry is None:
        entry = schedule.get(DAY_NAMES[weekday])
    return entry if isinstance(entry, dict) else None


def validate_sales_csv(
    parsed: CsvReadResult,
    mapping: Mapping[str, str | None],
    *,
    order_identity: str = "global",
    schedule: Mapping[Any, Any] | None = None,
    schedule_confirmed: bool = False,
    confirm_open_no_sales: bool = False,
) -> ValidationResult:
    """Validate a mapped CSV without removing or changing its original rows.

    Invalid date/quantity rows are omitted only from ``analysis_frame`` and are
    explicitly reported. Exact duplicate lines remain in that frame.
    """
    schedule = schedule or {}
    issues = list(parsed.issues)
    if order_identity not in ("global", "date_order"):
        issues.append(_issue("—", "pedido_id", order_identity, "Erro", "A configuração da identidade do pedido não é reconhecida.", "Escolha pedido_id global ou data + pedido_id."))
        order_identity = "global"
    present_mapping = {key: value for key, value in mapping.items() if value is not None and str(value) in parsed.headers}
    missing_required = [name for name in REQUIRED_COLUMNS if name not in present_mapping]
    selected_sources = list(present_mapping.values())
    reused_sources = {name for name in selected_sources if selected_sources.count(name) > 1}
    for source in sorted(reused_sources):
        issues.append(_issue(1, source, source, "Erro", "A mesma coluna de origem foi associada a mais de um campo.", "Escolha uma coluna diferente para cada campo ou desfaça o mapeamento."))
    if parsed.empty:
        issues.append(_issue(1, "arquivo", "", "Erro", "O arquivo está vazio ou contém somente o cabeçalho.", "Envie um CSV com ao menos uma linha de dados."))
    for name in missing_required:
        issues.append(_issue(1, name, "ausente", "Erro", f"O campo obrigatório '{name}' não foi mapeado.", "Mapeie uma coluna equivalente ou inclua o campo no CSV."))
    _, mapping_candidates = suggest_column_mapping(parsed.headers)
    for target, candidates in mapping_candidates.items():
        if len(candidates) > 1 and present_mapping.get(target) is None:
            issues.append(_issue(1, target, ", ".join(candidates), "Aviso", "Mais de uma coluna pode corresponder a este campo; o painel não escolheu uma automaticamente.", "Selecione a coluna correta no mapeamento antes de confirmar."))

    for name in CANONICAL_COLUMNS:
        if name not in present_mapping:
            if name in OPTIONAL_COLUMNS:
                issues.append(_issue("—", name, "coluna ausente", "Informação", "Este campo é opcional; a análise correspondente ficará indisponível.", "Inclua a coluna somente se o estabelecimento mantiver essa informação."))
            elif name in RECOMMENDED_COLUMNS:
                uses = {
                    "pedido_id": "KPIs por pedido e ticket médio",
                    "hora": "análise por horário",
                    "produto": "ranking de produtos",
                    "tamanho": "segmentação por tamanho",
                    "preco_unitario": "faturamento e ticket médio",
                    "categoria": "análise por categoria",
                }
                issues.append(_issue("—", name, "coluna ausente", "Aviso", f"Sem este campo, {uses[name]} não poderá ser calculado.", f"Inclua '{name}' se essa análise for necessária."))
        else:
            source = str(present_mapping[name])
            if source != name:
                issues.append(_issue(1, source, source, "Informação", f"A coluna '{source}' será mapeada para '{name}'.", "Confira o mapeamento antes de confirmar a importação."))

    if not parsed.frame.empty:
        for _, row in parsed.frame.loc[parsed.frame["__malformed__"].fillna(False)].iterrows():
            # Structural diagnostics are already in parsed. Keep these rows out of derived calculations.
            pass

    mapped = pd.DataFrame(index=parsed.frame.index)
    mapped["__csv_line__"] = parsed.frame.get("__csv_line__", pd.Series(dtype="int64"))
    mapped["__malformed__"] = parsed.frame.get("__malformed__", pd.Series(dtype="bool")).fillna(False).astype(bool)
    for target in CANONICAL_COLUMNS:
        source = present_mapping.get(target)
        mapped[target] = parsed.frame[source].astype("string").fillna("").str.strip() if source in parsed.frame.columns else ""

    parsed_dates, date_errors = parse_sales_dates(mapped["data"].tolist())
    for index, value in mapped["data"].items():
        parsed_date = parsed_dates[index]
        error = date_errors[index]
        if error:
            issues.append(_issue(mapped.at[index, "__csv_line__"], "data", value, "Erro", error.capitalize() + ".", "Use AAAA-MM-DD ou DD/MM/AAAA. Datas com dia e mês ambos até 12 só são interpretadas como brasileiras se outra data do arquivo identificar esse padrão; caso contrário, use ISO."))
        elif parsed_date and (parsed_date.year < 2000 or parsed_date.year > datetime.now().year + 1):
            issues.append(_issue(mapped.at[index, "__csv_line__"], "data", value, "Aviso", "A data está fora do intervalo usual de análise (2000 até o próximo ano).", "Confira se o ano foi digitado corretamente."))
    mapped["__parsed_date__"] = pd.to_datetime(parsed_dates)
    mapped["__date_error__"] = date_errors

    quantities: list[int | None] = []
    quantity_errors: list[str | None] = []
    for index, value in mapped["quantidade"].items():
        amount, error = _parse_integer(value)
        quantities.append(amount)
        quantity_errors.append(error)
        if error:
            issues.append(_issue(mapped.at[index, "__csv_line__"], "quantidade", value, "Erro", error.capitalize() + ".", "Informe um número inteiro positivo. Use a configuração do calendário para dias sem venda ou fechados; não inclua linhas comerciais com zero."))
    mapped["__parsed_quantity__"] = quantities
    mapped["__quantity_error__"] = quantity_errors

    prices: list[float | None] = []
    price_errors: list[str | None] = []
    thousands_normalized = 0
    for index, value in mapped["preco_unitario"].items():
        if _blank(value):
            price, error, normalized_thousands = None, "preço vazio", False
        else:
            price, error, normalized_thousands = _parse_price(value)
        prices.append(price)
        price_errors.append(error)
        thousands_normalized += int(normalized_thousands)
        if not _blank(value) and error:
            issues.append(_issue(mapped.at[index, "__csv_line__"], "preco_unitario", value, "Erro", error.capitalize() + ".", "Use um valor positivo sem símbolo de moeda, como 35.90 ou 35,90. Valores ambíguos precisam ser corrigidos na origem."))
        elif _blank(value) and "preco_unitario" in present_mapping:
            issues.append(_issue(mapped.at[index, "__csv_line__"], "preco_unitario", "vazio", "Aviso", "O preço desta linha está vazio; o faturamento completo não poderá ser calculado.", "Informe o preço unitário se esse registro deve participar do faturamento."))
    mapped["__parsed_price__"] = prices
    mapped["__price_error__"] = price_errors
    if thousands_normalized:
        issues.append(_issue("—", "preco_unitario", thousands_normalized, "Informação", "Alguns separadores de milhar foram reconhecidos por um padrão numérico explícito.", "Confira os valores no CSV original antes de confirmar."))

    normalized_times: list[str | None] = []
    time_errors: list[str | None] = []
    for index, value in mapped["hora"].items():
        parsed_time, error = _parse_time(value)
        normalized_times.append(parsed_time.strftime("%H:%M") if parsed_time else None)
        time_errors.append(error)
        if error:
            issues.append(_issue(mapped.at[index, "__csv_line__"], "hora", value, "Erro", error.capitalize() + ".", "Use HH ou HH:MM, sem alterar o horário original do arquivo."))
    for field in ("produto", "categoria", "tamanho"):
        if field in present_mapping:
            for index, value in mapped[field].items():
                if _blank(value):
                    issues.append(_issue(mapped.at[index, "__csv_line__"], field, "vazio", "Aviso", f"O campo {field} está vazio nesta linha.", f"Preencha {field} se essa análise for necessária."))
    mapped["__parsed_time__"] = normalized_times
    mapped["__time_error__"] = time_errors

    normalized_ids = mapped["pedido_id"].astype("string").str.strip().replace("", pd.NA)
    mapped["__normalized_order_id__"] = normalized_ids
    duplicate_rows = pd.DataFrame()
    usable_for_duplicate_check = mapped.loc[
        mapped["__parsed_date__"].notna()
        & mapped["__parsed_quantity__"].notna()
        & ~mapped["__malformed__"]
    ].copy()
    duplicate_columns = [name for name in CANONICAL_COLUMNS if name in present_mapping]
    if duplicate_columns and not usable_for_duplicate_check.empty:
        duplicate_mask = usable_for_duplicate_check.duplicated(subset=duplicate_columns, keep=False)
        duplicate_rows = usable_for_duplicate_check.loc[duplicate_mask, ["__csv_line__", *duplicate_columns]].copy()
        if not duplicate_rows.empty:
            groups = usable_for_duplicate_check.loc[duplicate_mask].groupby(duplicate_columns, dropna=False, sort=False)
            for duplicate_group in groups:
                group_frame = duplicate_group[1]
                lines = group_frame["__csv_line__"].astype(str).tolist()
                for _, row in group_frame.iterrows():
                    issues.append(_issue(row["__csv_line__"], "registro", " | ".join(str(row.get(col, "")) for col in duplicate_columns[:4]), "Aviso", f"Linha aparentemente igual a outra(s) nas linhas {', '.join(lines)}. Isso é apenas uma suspeita; nenhuma linha será excluída.", "Confira no sistema de caixa. Mantenha ou corrija manualmente conforme a origem."))

    valid_dated = mapped.loc[mapped["__parsed_date__"].notna() & ~mapped["__malformed__"]].copy()
    valid_dates = valid_dated["__parsed_date__"].dropna()
    observed_dates = set(valid_dates.tolist())
    dates_with_bad_quantity = set(
        mapped.loc[mapped["__parsed_date__"].notna() & mapped["__quantity_error__"].notna(), "__parsed_date__"].tolist()
    )
    dates_with_malformed_rows = set(
        mapped.loc[mapped["__parsed_date__"].notna() & mapped["__malformed__"], "__parsed_date__"].tolist()
    )
    dates_with_valid_sales = set(
        mapped.loc[mapped["__parsed_date__"].notna() & mapped["__parsed_quantity__"].notna(), "__parsed_date__"].tolist()
    )
    missing_id_count = int(normalized_ids.isna().sum()) if "pedido_id" in present_mapping else int(len(mapped))
    if "pedido_id" in present_mapping and missing_id_count:
        for index in normalized_ids.index[normalized_ids.isna()]:
            issues.append(_issue(mapped.at[index, "__csv_line__"], "pedido_id", "vazio", "Aviso", "Esta linha não tem identificador de pedido.", "A linha pode contribuir para unidades/dia, mas não entra na contagem de pedidos. Ticket e unidades por pedido ficam indisponíveis se a identificação estiver incompleta."))

    id_dates = valid_dated.assign(__order_id=normalized_ids.loc[valid_dated.index]).dropna(subset=["__order_id"])
    cross_date_ids: dict[str, list[int]] = {}
    closed_dates_with_sales: set[pd.Timestamp] = set()
    for order_id, group in id_dates.groupby("__order_id", sort=False):
        distinct_dates = group["__parsed_date__"].dropna().unique()
        if len(distinct_dates) > 1:
            cross_date_ids[str(order_id)] = group["__csv_line__"].astype(int).tolist()
            kind = "Aviso" if order_identity == "global" else "Informação"
            explanation = (
                "O mesmo pedido_id aparece em datas diferentes; com a identidade global, essas linhas contam como um pedido."
                if order_identity == "global"
                else "O mesmo pedido_id aparece em datas diferentes; a identidade data + pedido_id contará um pedido por data."
            )
            for _, row in group.iterrows():
                issues.append(_issue(row["__csv_line__"], "pedido_id", order_id, kind, explanation, "Confira se o sistema reutiliza números diariamente. O identificador original será preservado."))

    schedule_valid = True
    closed_weekdays: list[int] = []
    if not schedule_confirmed:
        schedule_valid = False
        issues.append(_issue("—", "calendário", "não confirmado", "Aviso", "Dias e horários de funcionamento ainda não foram confirmados.", "Revise a agenda do estabelecimento. A previsão não será liberada até a confirmação."))
    else:
        for weekday in range(7):
            entry = _schedule_entry(schedule, weekday)
            if entry is None or "is_open" not in entry:
                schedule_valid = False
                issues.append(_issue("—", DAY_NAMES[weekday], "configuração ausente", "Erro", "Não há configuração confirmada para este dia da semana.", "Configure se a pizzaria abre e seus horários."))
                continue
            if not bool(entry.get("is_open")):
                closed_weekdays.append(weekday)
                continue
            start_time, start_error = _parse_time(entry.get("opens_at"))
            end_time, end_error = _parse_time(entry.get("closes_at"))
            if start_error or end_error or start_time is None or end_time is None or start_time == end_time:
                schedule_valid = False
                issues.append(_issue("—", DAY_NAMES[weekday], f"{entry.get('opens_at')}–{entry.get('closes_at')}", "Erro", "Horário de abertura/fechamento inválido para um dia marcado como aberto.", "Informe horários HH:MM diferentes ou marque o dia como fechado."))

    if schedule_confirmed and schedule_valid:
        for index, row in mapped.loc[mapped["__parsed_date__"].notna() & mapped["__parsed_time__"].notna()].iterrows():
            day = int(row["__parsed_date__"].day_of_week)
            entry = _schedule_entry(schedule, day)
            if entry is None:
                continue
            parsed_time, _ = _parse_time(row["hora"])
            if parsed_time is None:
                continue
            line = row["__csv_line__"]
            if not bool(entry.get("is_open")):
                closed_dates_with_sales.add(pd.Timestamp(row["__parsed_date__"]))
                issues.append(_issue(line, "hora", row["hora"], "Aviso", f"Há uma venda registrada em {DAY_NAMES[day]}, dia configurado como fechado.", "Confira o calendário e o registro. O dado original não será alterado."))
            else:
                opens_at, _ = _parse_time(entry.get("opens_at"))
                closes_at, _ = _parse_time(entry.get("closes_at"))
                if opens_at and closes_at and not _time_in_schedule(parsed_time, opens_at, closes_at):
                    issues.append(_issue(line, "hora", row["hora"], "Aviso", f"O horário está fora do funcionamento configurado para {DAY_NAMES[day]}.", "Confira o horário de funcionamento ou o registro. Nenhum horário será ajustado automaticamente."))

    unknown_dates: set[pd.Timestamp] = set()
    confirmed_zero_dates: set[pd.Timestamp] = set()
    unlocated_critical_rows = int(sum(error is not None for error in date_errors)) + int(
        (mapped["__malformed__"] & mapped["__parsed_date__"].isna()).sum()
    )
    if unlocated_critical_rows and not valid_dates.empty:
        issues.append(_issue("—", "data", unlocated_critical_rows, "Aviso", "Há linha(s) com data inválida ou estrutura incompleta que não podem ser associadas a um dia específico; os pontos temporais do período ficam desconhecidos.", "Corrija a data ou a estrutura no CSV original e reenvie. A série não preencherá esses dias com zero."))
    if not valid_dates.empty:
        calendar = pd.date_range(valid_dates.min(), valid_dates.max(), freq="D")
        for day in calendar:
            if unlocated_critical_rows:
                unknown_dates.add(day)
                continue
            if day in dates_with_malformed_rows:
                unknown_dates.add(day)
                continue
            entry = _schedule_entry(schedule, int(day.day_of_week)) if schedule_confirmed and schedule_valid else None
            has_any_rows = day in observed_dates
            has_bad_quantity = day in dates_with_bad_quantity
            if has_bad_quantity:
                unknown_dates.add(day)
                continue
            if not has_any_rows:
                if entry is None:
                    unknown_dates.add(day)
                    issues.append(_issue("—", "data", day.strftime("%Y-%m-%d"), "Aviso", "Não há registro e o calendário não permite saber se houve venda ou se o estabelecimento estava fechado.", "Confirme o calendário e, para dias abertos sem venda, confirme explicitamente que o zero é correto."))
                elif not bool(entry.get("is_open")):
                    confirmed_zero_dates.add(day)
                elif confirm_open_no_sales:
                    confirmed_zero_dates.add(day)
                    issues.append(_issue("—", "data", day.strftime("%Y-%m-%d"), "Informação", "Dia aberto sem linha confirmado pelo usuário como zero vendas.", "Nenhuma linha transacional foi criada; o zero fica somente na série temporal."))
                else:
                    unknown_dates.add(day)
                    issues.append(_issue("—", "data", day.strftime("%Y-%m-%d"), "Aviso", "Dia configurado como aberto sem registro; o volume é desconhecido até confirmação.", "Confirme que não houve vendas para usar zero, ou corrija/exporte os registros desse dia."))
            elif entry is not None and not bool(entry.get("is_open")):
                unknown_dates.add(day)
                if day not in closed_dates_with_sales:
                    for _, dated_row in valid_dated.loc[valid_dated["__parsed_date__"].eq(day)].iterrows():
                        closed_dates_with_sales.add(day)
                        issues.append(_issue(dated_row["__csv_line__"], "data", day.strftime("%Y-%m-%d"), "Aviso", f"Há registros em {DAY_NAMES[int(day.day_of_week)]}, dia configurado como fechado.", "Confira o calendário e o registro. O dado original não será alterado."))

    analysis_rows: list[dict[str, Any]] = []
    for index, row in mapped.iterrows():
        if bool(row["__malformed__"]) or pd.isna(row["__parsed_date__"]) or pd.isna(row["__parsed_quantity__"]):
            continue
        analysis_row: dict[str, Any] = {
            "data": pd.Timestamp(row["__parsed_date__"]).normalize(),
            "quantidade": str(int(row["__parsed_quantity__"])),
        }
        for name in CANONICAL_COLUMNS[2:]:
            if name not in present_mapping:
                continue
            value = row[name]
            if name == "pedido_id":
                analysis_row[name] = "" if _blank(value) else str(value).strip()
            elif name == "hora":
                analysis_row[name] = row["__parsed_time__"] if not row["__time_error__"] else str(value).strip()
            elif name == "preco_unitario":
                analysis_row[name] = "" if row["__parsed_price__"] is None else f"{float(row['__parsed_price__']):.2f}"
            else:
                analysis_row[name] = "" if _blank(value) else str(value).strip()
        analysis_rows.append(analysis_row)
    analysis_frame = pd.DataFrame(analysis_rows)
    if not analysis_frame.empty:
        analysis_frame["data"] = pd.to_datetime(analysis_frame["data"], errors="coerce").dt.normalize()

    invalid_date_or_quantity = bool(any(date_errors) or any(quantity_errors))
    structural_errors = any(issue.get("Coluna") == "estrutura" and issue.get("Tipo") == "Erro" for issue in issues)
    invalid_prices = any(error for error in price_errors if error not in (None, "preço vazio"))
    all_positive_sales_priced = (
        "preco_unitario" in present_mapping
        and len(mapped) > 0
        and all(
            (mapped.at[index, "__parsed_price__"] is not None)
            for index in mapped.index
            if not _blank(mapped.at[index, "quantidade"])
            and mapped.at[index, "__quantity_error__"] is None
            and mapped.at[index, "__date_error__"] is None
            and not bool(mapped.at[index, "__malformed__"])
        )
        and not invalid_prices
        and not invalid_date_or_quantity
        and not structural_errors
    )
    revenue_available = bool(all_positive_sales_priced and not analysis_frame.empty)
    if "pedido_id" in present_mapping:
        valid_ids = analysis_frame.get("pedido_id", pd.Series(dtype="string")).astype("string").str.strip().replace("", pd.NA)
    else:
        valid_ids = pd.Series([pd.NA] * len(analysis_frame), dtype="string")
    order_keys = []
    for index, row in analysis_frame.iterrows():
        order_id = valid_ids.iloc[index] if index < len(valid_ids) else pd.NA
        if pd.isna(order_id):
            order_keys.append(pd.NA)
        elif order_identity == "date_order":
            order_keys.append(f"{pd.Timestamp(row['data']).strftime('%Y-%m-%d')}|{order_id}")
        else:
            order_keys.append(str(order_id))
    unique_orders = int(pd.Series(order_keys, dtype="string").nunique(dropna=True))
    product_values = analysis_frame.get("produto", pd.Series(dtype="string")).astype("string").str.strip()
    category_values = analysis_frame.get("categoria", pd.Series(dtype="string")).astype("string").str.strip()
    size_values = analysis_frame.get("tamanho", pd.Series(dtype="string")).astype("string").str.strip()
    quantity_values = pd.to_numeric(analysis_frame.get("quantidade", pd.Series(dtype="string")), errors="coerce")

    product_variants: list[tuple[str, str]] = []
    distinct_products = sorted({value for value in product_values.dropna().tolist() if value})
    normalized_products = {value: normalize_column_name(value) for value in distinct_products}
    for first_index, first in enumerate(distinct_products):
        for second in distinct_products[first_index + 1:]:
            left, right = normalized_products[first], normalized_products[second]
            similar = left == right or SequenceMatcher(None, left, right).ratio() >= 0.93
            if first.strip() != second.strip() and min(len(left), len(right)) >= 5 and similar:
                product_variants.append((first, second))
    for first, second in product_variants:
        first_lines = mapped.loc[mapped["produto"].eq(first), "__csv_line__"].astype(str).tolist()[:10]
        second_lines = mapped.loc[mapped["produto"].eq(second), "__csv_line__"].astype(str).tolist()[:10]
        issues.append(_issue(
            ", ".join([*first_lines, *second_lines]) or "—",
            "produto",
            f"{first} / {second}",
            "Aviso",
            "Foram encontrados nomes muito parecidos; podem ser grafias diferentes do mesmo produto.",
            "Confira o cardápio antes de unificar nomes. O painel não substitui nem agrupa esses nomes automaticamente.",
        ))

    if analysis_frame.empty and not missing_required:
        issues.append(_issue("—", "arquivo", "sem linhas válidas", "Erro", "Não há linha com data e quantidade válidas para análise de volume.", "Corrija as datas/quantidades no CSV original e reenvie-o."))

    issue_frame = pd.DataFrame(issues, columns=ISSUE_COLUMNS)
    if not issue_frame.empty:
        for column in ISSUE_COLUMNS:
            issue_frame[column] = issue_frame[column].astype("string").fillna("")
    error_count = int(issue_frame["Tipo"].eq("Erro").sum()) if not issue_frame.empty else 0
    warning_count = int(issue_frame["Tipo"].eq("Aviso").sum()) if not issue_frame.empty else 0
    header_errors = any(issue.get("Coluna") == "cabeçalho" and issue.get("Tipo") == "Erro" for issue in issues)
    mapping_ready = not missing_required and not reused_sources and not parsed.empty and not header_errors
    valid_date_count = int(mapped["__parsed_date__"].notna().sum())
    valid_quantity_count = int(mapped["__parsed_quantity__"].notna().sum())
    summary = {
        "total_rows": int(len(parsed.frame)),
        "valid_analysis_rows": int(len(analysis_frame)),
        "valid_date_rows": valid_date_count,
        "valid_quantity_rows": valid_quantity_count,
        "invalid_date_rows": int(sum(error is not None for error in date_errors)),
        "invalid_quantity_rows": int(sum(error is not None for error in quantity_errors)),
        "invalid_price_rows": int(sum(error not in (None, "preço vazio") for error in price_errors)),
        "missing_price_rows": int(sum(error == "preço vazio" for error in price_errors)),
        "missing_order_id_rows": int(missing_id_count),
        "distinct_orders": unique_orders,
        "units": int(quantity_values.sum()) if quantity_values.notna().any() else 0,
        "products": int(product_values.replace("", pd.NA).nunique(dropna=True)),
        "categories": int(category_values.replace("", pd.NA).nunique(dropna=True)),
        "sizes": sorted({str(value) for value in size_values.dropna().tolist() if str(value)}),
        "product_names": distinct_products,
        "duplicate_groups": int(duplicate_rows.groupby(duplicate_columns, dropna=False).ngroups) if not duplicate_rows.empty else 0,
        "duplicate_affected_rows": int(len(duplicate_rows)),
        "cross_date_order_ids": len(cross_date_ids),
        "date_start": valid_dates.min() if not valid_dates.empty else None,
        "date_end": valid_dates.max() if not valid_dates.empty else None,
        "unknown_days": len(unknown_dates),
        "unknown_dates": sorted(unknown_dates),
        "confirmed_zero_dates": sorted(confirmed_zero_dates),
        "errors": error_count,
        "warnings": warning_count,
        "information": int(issue_frame["Tipo"].eq("Informação").sum()) if not issue_frame.empty else 0,
        "revenue_available": revenue_available,
        "order_identity": order_identity,
        "product_variants": product_variants,
        "closed_dates_with_sales": sorted(closed_dates_with_sales),
    }
    forecast_ready = bool(
        mapping_ready
        and schedule_confirmed
        and schedule_valid
        and not unknown_dates
        and not invalid_date_or_quantity
        and not structural_errors
        and not analysis_frame.empty
        and valid_dates.max() - valid_dates.min() >= pd.Timedelta(days=55)
    ) if not valid_dates.empty else False
    if not mapping_ready or analysis_frame.empty:
        status = "Arquivo incompatível até correção"
    elif error_count or warning_count:
        status = "Apto para análise com ressalvas"
    else:
        status = "Apto para análise"

    if duplicate_rows.empty:
        duplicate_preview = pd.DataFrame()
    else:
        duplicate_preview = duplicate_rows.rename(columns={"__csv_line__": "Número da linha original"}).copy()
    return ValidationResult(
        analysis_frame=analysis_frame,
        mapped_frame=mapped,
        issues=issue_frame,
        duplicate_rows=duplicate_preview,
        summary=summary,
        unknown_dates=sorted(unknown_dates),
        closed_weekdays=tuple(closed_weekdays),
        revenue_available=revenue_available,
        forecast_ready=forecast_ready,
        mapping_ready=mapping_ready,
        status=status,
    )


def schedule_from_rows(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Convert editable weekday rows to a weekday-indexed configuration."""
    result: dict[int, dict[str, Any]] = {}
    day_lookup = {name: index for index, name in enumerate(DAY_NAMES)}
    for row in rows:
        day = row.get("dia") or row.get("Dia")
        if day not in day_lookup:
            continue
        result[day_lookup[day]] = {
            "is_open": bool(row.get("aberto", row.get("Abre?", False))),
            "opens_at": str(row.get("abre", row.get("Abertura", ""))),
            "closes_at": str(row.get("fecha", row.get("Fechamento", ""))),
        }
    return result

