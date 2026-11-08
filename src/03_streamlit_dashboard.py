"""Painel Streamlit para análise de vendas de pizzarias.

A fonte padrão são as sete tabelas normalizadas em data/normalized/. Também aceita
um CSV simples, quatro CSVs de outra pizzaria ou consultas somente de leitura ao SQL Server.
"""

from __future__ import annotations

import importlib.util
import hashlib
import io
import os
import re
import sqlite3
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import create_engine, text
try:
    # `streamlit run src/03_streamlit_dashboard.py` places `src/` on sys.path.
    from pizzeria_import import (
        CANONICAL_COLUMNS as IMPORT_COLUMNS,
        DAY_NAMES as IMPORT_DAY_NAMES,
        parse_sales_csv,
        parse_sales_dates,
        schedule_from_rows,
        suggest_column_mapping,
        validate_sales_csv,
    )
except ModuleNotFoundError as import_error:
    # AppTest and package-based entry points may expose the project root instead.
    if import_error.name != "pizzeria_import":
        raise
    from src.pizzeria_import import (
        CANONICAL_COLUMNS as IMPORT_COLUMNS,
        DAY_NAMES as IMPORT_DAY_NAMES,
        parse_sales_csv,
        parse_sales_dates,
        schedule_from_rows,
        suggest_column_mapping,
        validate_sales_csv,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = PROJECT_ROOT / "src" / "02_regressao_linear_vendas_diarias.py"
NORMALIZED_DATA_DIR = PROJECT_ROOT / "data" / "normalized"
ANALYSIS_QUERIES_PATH = PROJECT_ROOT / "03_analysis_queries.sql"
CASE_STUDY_CSV_PATH = PROJECT_ROOT / "output" / "VENDAS_PIZZARIA_BAIRRO.csv"
CSV_TEMPLATE_PATH = PROJECT_ROOT / "docs" / "modelo_csv_vendas_pizzaria.csv"
MODE_PUBLIC = "Base pública original do projeto"
MODE_CASE_STUDY = "Estudo de caso — VENDAS_PIZZARIA_BAIRRO"
MODE_CUSTOM_CSV = "Carregar CSV de outra pizzaria"
MODE_FOUR_CSVS = "Enviar quatro CSVs da pizzaria"
MODE_SQL_SERVER = "Banco SQL Server normalizado"
NORMALIZED_TABLES = (
    "categories",
    "pizza_types",
    "ingredients",
    "pizza_type_ingredients",
    "pizzas",
    "orders",
    "order_details",
)
QUERY_MARKER = re.compile(r"(?m)^--\s*(\d+\.\d+)\.\s*(.*?)\s*$")
DAY_NAMES = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
REQUIRED_UPLOADS = {
    "orders": {"order_id", "date", "time"},
    "order_details": {"order_id", "pizza_id", "quantity"},
    "pizzas": {"pizza_id", "pizza_type_id", "size", "price"},
    "pizza_types": {"pizza_type_id", "name", "category"},
}
SIMPLE_CSV_ALIASES = {
    "date": {"date", "data", "data_pedido", "data_venda"},
    "quantity": {"quantity", "quantidade", "qtd", "qtde", "quantidade_vendida", "unidades_vendidas"},
    "order_id": {"order_id", "pedido_id", "id_pedido", "numero_pedido", "pedido"},
    "time": {"time", "hora", "horario", "hora_pedido"},
    "product": {"product", "produto", "pizza", "sabor", "nome_pizza", "nome_produto", "product_name"},
    "size": {"size", "tamanho", "tamanho_pizza"},
    "unit_price": {"unit_price", "price", "preco", "preco_unitario", "valor_unitario", "preco_venda"},
    "category": {"category", "categoria"},
    "ingredients": {"ingredients", "ingredientes"},
}


st.set_page_config(
    page_title="Painel de Análise de Dados para Pizzarias | UNIVESP",
    page_icon="🍕",
    layout="wide",
    initial_sidebar_state="expanded",
)


def read_csv_path(path: Path, *, latin1_fallback: bool = False) -> pd.DataFrame:
    """Lê CSV UTF-8 e, se necessário, tenta a codificação usada pela base original."""
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        if latin1_fallback:
            return pd.read_csv(path, encoding="latin1")
        raise


def read_uploaded_csv(uploaded_file, *, latin1_fallback: bool = False) -> pd.DataFrame:
    try:
        return pd.read_csv(uploaded_file, encoding="utf-8-sig")
    except UnicodeDecodeError:
        if latin1_fallback:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, encoding="latin1")
        raise


def read_single_sales_csv(uploaded_file) -> pd.DataFrame:
    """Lê CSV como texto para preservar IDs, inclusive zeros à esquerda."""
    uploaded_file.seek(0)
    try:
        return pd.read_csv(uploaded_file, sep=None, engine="python", encoding="utf-8-sig", dtype=str, keep_default_na=False)
    except UnicodeDecodeError:
        uploaded_file.seek(0)
        return pd.read_csv(uploaded_file, sep=None, engine="python", encoding="latin1", dtype=str, keep_default_na=False)


def normalize_column_name(value: str) -> str:
    without_accents = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", without_accents.lower()).strip("_")


def parse_localized_numbers(values: pd.Series) -> pd.Series:
    """Converte números com ponto ou vírgula decimal para valores numéricos."""
    def parse_one(value):
        if pd.isna(value):
            return np.nan
        cleaned = str(value).strip().replace("R$", "").replace("$", "").replace(" ", "")
        if not cleaned:
            return np.nan
        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")
        return pd.to_numeric(cleaned, errors="coerce")

    return values.map(parse_one).astype(float)


def build_daily_sales_series(
    frame: pd.DataFrame,
    start_date,
    end_date,
    *,
    closed_weekdays: tuple[int, ...] = (),
) -> pd.DataFrame:
    """Agrega itens transacionais em uma série diária completa, sem criar pedidos."""
    calendar = pd.date_range(
        pd.Timestamp(start_date).normalize(),
        pd.Timestamp(end_date).normalize(),
        freq="D",
    )
    transactions = frame.dropna(subset=["date", "quantity"]).copy()
    transactions = transactions.loc[transactions["quantity"].gt(0)]
    daily = (
        transactions.groupby("date")["quantity"].sum()
        .reindex(calendar, fill_value=0)
        .astype(float)
    )
    if closed_weekdays:
        daily.loc[daily.index.day_of_week.isin(closed_weekdays)] = 0.0
    result = daily.rename_axis("date").reset_index(name="quantity")
    return result


def predict_pizzeria_recursively(
    model_module,
    model,
    history: pd.Series,
    dates: pd.DatetimeIndex,
    origin_date: pd.Timestamp,
    *,
    closed_weekdays: tuple[int, ...],
) -> tuple[np.ndarray, pd.DataFrame]:
    """Aplica os fechamentos da pizzaria ao redor do preditor original."""
    working_history = history.astype(float).copy()
    predictions: list[float] = []
    feature_rows: list[pd.DataFrame] = []
    for date in pd.DatetimeIndex(dates):
        prediction, features = model_module.predict_recursively(
            model,
            working_history,
            pd.DatetimeIndex([date]),
            origin_date,
        )
        value = 0.0 if date.day_of_week in closed_weekdays else max(float(prediction[0]), 0.0)
        predictions.append(value)
        feature_rows.append(features)
        working_history.loc[date] = value
    return np.asarray(predictions), pd.concat(feature_rows)


def evaluate_pizzeria_walk_forward(
    model_module,
    daily: pd.DataFrame,
    test_size: int,
    *,
    closed_weekdays: tuple[int, ...],
) -> tuple[dict[str, float], pd.DataFrame]:
    """Avalia a previsão da pizzaria respeitando os dias fechados informados."""
    origin_date = pd.Timestamp(daily["date"].iloc[0])
    split_at = len(daily) - test_size
    history = daily.iloc[:split_at].set_index("date")["quantity"].astype(float)
    test = daily.iloc[split_at:].reset_index(drop=True)
    predictions: list[float] = []
    baselines: list[float] = []

    for start in range(0, len(test), 7):
        block = test.iloc[start : start + 7]
        x_train, y_train = model_module.make_training_data(history, origin_date)
        model = model_module.LinearRegression().fit(x_train, y_train)
        block_dates = pd.DatetimeIndex(block["date"])
        block_predictions, _ = predict_pizzeria_recursively(
            model_module,
            model,
            history,
            block_dates,
            origin_date,
            closed_weekdays=closed_weekdays,
        )
        predictions.extend(block_predictions.tolist())
        baselines.extend(
            float(history.loc[date - pd.Timedelta(days=7)]) for date in block_dates
        )
        actual_block = block.set_index("date")["quantity"].astype(float)
        history = pd.concat([history, actual_block])

    actual = test["quantity"].to_numpy(dtype=float)
    predictions_array = np.asarray(predictions)
    baseline_array = np.asarray(baselines)
    metrics = {
        "mae": float(model_module.mean_absolute_error(actual, predictions_array)),
        "rmse": float(np.sqrt(model_module.mean_squared_error(actual, predictions_array))),
        "r2": float(model_module.r2_score(actual, predictions_array)),
        "baseline_mae": float(model_module.mean_absolute_error(actual, baseline_array)),
    }
    backtest = pd.DataFrame(
        {"date": test["date"], "actual": actual, "predicted": predictions_array}
    )
    return metrics, backtest


def prepare_simple_sales(uploaded_file) -> tuple[pd.DataFrame, dict[str, int]]:
    """Carrega um único CSV com date/quantity e usa campos adicionais quando existirem."""
    raw = read_single_sales_csv(uploaded_file)
    if raw.empty:
        raise ValueError("O CSV não contém linhas de venda.")

    aliases = {
        alias: canonical
        for canonical, names in SIMPLE_CSV_ALIASES.items()
        for alias in names
    }
    renames: dict[str, str] = {}
    found: dict[str, str] = {}
    for column in raw.columns:
        canonical = aliases.get(normalize_column_name(column))
        if canonical:
            if canonical in found:
                raise ValueError(
                    f"Há mais de uma coluna para '{canonical}': '{found[canonical]}' e '{column}'. "
                    "Mantenha apenas uma delas."
                )
            found[canonical] = str(column)
            renames[column] = canonical
    frame = raw.rename(columns=renames).copy()
    missing = {"date", "quantity"}.difference(frame.columns)
    if missing:
        raise ValueError(
            "O CSV simples precisa ter pelo menos data e quantidade. "
            "Use cabeçalhos como 'data' e 'quantidade' ou 'date' e 'quantity'."
        )

    parsed_dates, date_errors = parse_sales_dates(frame["date"].tolist())
    frame["date"] = pd.Series(parsed_dates, index=frame.index, dtype="datetime64[ns]").dt.normalize()
    if frame["date"].isna().any():
        bad_rows = [int(index) + 2 for index, error in enumerate(date_errors) if error is not None][:5]
        raise ValueError(f"Há datas inválidas no CSV (linha(s): {bad_rows}).")
    calendar_days = pd.date_range(frame["date"].min(), frame["date"].max(), freq="D")
    days_without_rows = len(calendar_days.difference(pd.DatetimeIndex(frame["date"].drop_duplicates())))

    frame["quantity"] = parse_localized_numbers(frame["quantity"])
    if frame["quantity"].isna().any():
        bad_rows = (frame.index[frame["quantity"].isna()] + 2).tolist()[:5]
        raise ValueError(f"Há quantidades vazias ou inválidas no CSV (linha(s): {bad_rows}).")
    if (frame["quantity"] < 0).any():
        raise ValueError("A quantidade não pode ser negativa. Use zero para um dia sem vendas.")

    for column in ("order_id", "time", "product", "category", "size", "ingredients"):
        if column not in frame:
            frame[column] = pd.NA
        frame[column] = frame[column].astype("string").str.strip().replace("", pd.NA)

    if "unit_price" in frame:
        frame["price"] = parse_localized_numbers(frame["unit_price"])
        if (frame["price"].dropna() < 0).any():
            raise ValueError("O preço unitário não pode ser negativo.")
    else:
        frame["price"] = np.nan

    frame["size"] = frame["size"].str.upper()
    frame["revenue"] = frame["quantity"] * frame["price"]
    frame.loc[frame["quantity"].eq(0) & frame["price"].isna(), "revenue"] = 0
    frame["product"] = frame["product"].astype("string")
    has_product_and_size = frame["product"].notna() & frame["size"].notna()
    frame.loc[has_product_and_size, "product"] = (
        frame.loc[has_product_and_size, "product"] + " - " + frame.loc[has_product_and_size, "size"]
    )

    timestamps = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    has_time_value = frame["time"].notna()
    timestamps.loc[has_time_value] = pd.to_datetime(
        frame.loc[has_time_value, "date"].dt.strftime("%Y-%m-%d")
        + " "
        + frame.loc[has_time_value, "time"],
        errors="coerce",
    )
    valid_times = int(timestamps.notna().sum())
    invalid_times = int((frame["time"].notna() & timestamps.isna()).sum())
    frame["order_datetime"] = timestamps
    frame["hour"] = timestamps.dt.hour
    frame["weekday_num"] = frame["date"].dt.day_of_week
    frame["weekday"] = pd.Categorical(
        frame["weekday_num"].map(dict(enumerate(DAY_NAMES))),
        categories=DAY_NAMES,
        ordered=True,
    )

    missing_price_on_sales = frame["price"].isna() & frame["quantity"].gt(0)
    complete_prices = bool(
        not missing_price_on_sales.any()
        and (frame["price"].notna() & frame["quantity"].gt(0)).any()
    )
    valid_order_items = frame["order_id"].notna() & frame["quantity"].gt(0)
    quality = {
        "linhas do CSV recebido": int(len(frame)),
        "dias sem linha entre a primeira e a última data": int(days_without_rows),
        "linhas com horário inválido": invalid_times,
        "linhas sem preço unitário": int(frame["price"].isna().sum()),
        "linhas vendidas sem preço unitário": int(missing_price_on_sales.sum()),
        "linhas sem identificador de pedido": int(frame["order_id"].isna().sum()),
        "linhas sem produto": int(frame["product"].isna().sum()),
        "linhas sem categoria": int(frame["category"].isna().sum()),
        "linhas sem tamanho": int(frame["size"].isna().sum()),
        "coluna de preço completa": int(complete_prices),
        "linhas com pedido_id preenchido": int(frame["order_id"].notna().sum()),
        "linhas comerciais válidas": int(valid_order_items.sum()),
        "pedidos distintos válidos": int(frame.loc[valid_order_items, "order_id"].nunique()),
        "linhas com quantidade zero": int(frame["quantity"].eq(0).sum()),
        "horários válidos disponíveis": valid_times,
        "produtos informados": int(frame["product"].nunique(dropna=True)),
        "categorias informadas": int(frame["category"].nunique(dropna=True)),
        "ingredientes informados": int(frame["ingredients"].notna().sum()),
        "regras específicas do ETL de exemplo aplicadas": 0,
    }
    return frame.reset_index(drop=True), quality


def validate_table(name: str, dataframe: pd.DataFrame) -> None:
    required = REQUIRED_UPLOADS[name]
    missing = required.difference(dataframe.columns)
    if missing:
        raise ValueError(
            f"O arquivo {name}.csv precisa conter: {', '.join(sorted(required))}. "
            f"Campos ausentes: {', '.join(sorted(missing))}."
        )
    if dataframe.empty:
        raise ValueError(f"O arquivo {name}.csv não contém linhas.")


def normalize_catalog(
    pizza_types: pd.DataFrame,
    *,
    apply_project_recipe_rules: bool = True,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Reproduz em memória a normalização de categorias e ingredientes do ETL do projeto.

    O painel mantém as mesmas tabelas lógicas do modelo relacional: categories,
    pizza_types, ingredients e pizza_type_ingredients. Nenhum arquivo ou banco é gravado.
    """
    types = pizza_types[
        [column for column in ["pizza_type_id", "name", "category", "ingredients"]
         if column in pizza_types.columns]
    ].copy()
    if types[["name", "category"]].isna().any().any():
        raise ValueError("pizza_types contém nome ou categoria vazios; corrija o catálogo antes da análise.")
    types["name"] = types["name"].astype(str).str.strip()
    types["category"] = types["category"].astype(str).str.strip()
    if types[["name", "category"]].eq("").any().any():
        raise ValueError("pizza_types contém nome ou categoria em branco após remover espaços.")

    categories = (
        types[["category"]]
        .drop_duplicates()
        .rename(columns={"category": "category_name"})
        .reset_index(drop=True)
    )
    categories["category_id"] = range(1, len(categories) + 1)
    types = types.merge(
        categories,
        left_on="category",
        right_on="category_name",
        how="left",
        validate="many_to_one",
    )
    normalized_types = types[["pizza_type_id", "name", "category_id"]].copy()

    ingredient_dimension = pd.DataFrame(columns=["ingredient_id", "ingredient_name"])
    recipe_links = pd.DataFrame(columns=["pizza_type_id", "ingredient_id"])
    artichoke_standardizations = 0
    if "ingredients" in types.columns:
        original_recipe = types[["pizza_type_id", "ingredients"]].copy()
        recipe_lines = original_recipe.assign(
            ingredient=original_recipe["ingredients"].fillna("").astype(str).str.split(",")
        ).explode("ingredient")
        recipe_lines["ingredient"] = recipe_lines["ingredient"].astype(str).str.strip()
        artichoke_standardizations = int(recipe_lines["ingredient"].eq("Artichoke").sum())
        recipe_lines["ingredient"] = recipe_lines["ingredient"].replace(
            {"Artichoke": "Artichokes"}
        )
        recipe_lines = recipe_lines.loc[recipe_lines["ingredient"].ne("")]

        recipe_lines = recipe_lines[["pizza_type_id", "ingredient"]]
        if apply_project_recipe_rules:
            # Regra já definida no ETL do grupo: toda receita recebe Mozzarella Cheese.
            mozzarella = pd.DataFrame(
                {"pizza_type_id": types["pizza_type_id"], "ingredient": "Mozzarella Cheese"}
            )
            # Só acrescenta Tomato Sauce quando a receita original não cita outro molho.
            recipes_without_sauce = original_recipe.loc[
                ~original_recipe["ingredients"].fillna("").astype(str).str.contains("Sauce", case=False),
                "pizza_type_id",
            ]
            tomato_sauce = pd.DataFrame(
                {"pizza_type_id": recipes_without_sauce, "ingredient": "Tomato Sauce"}
            )
            recipe_lines = pd.concat(
                [recipe_lines, mozzarella, tomato_sauce],
                ignore_index=True,
            )
        recipe_lines = recipe_lines.drop_duplicates(subset=["pizza_type_id", "ingredient"])

        ingredient_dimension = (
            recipe_lines[["ingredient"]]
            .drop_duplicates()
            .rename(columns={"ingredient": "ingredient_name"})
            .reset_index(drop=True)
        )
        ingredient_dimension["ingredient_id"] = range(1, len(ingredient_dimension) + 1)
        recipe_links = (
            recipe_lines.merge(
                ingredient_dimension,
                left_on="ingredient",
                right_on="ingredient_name",
                how="left",
                validate="many_to_one",
            )[["pizza_type_id", "ingredient_id"]]
            .drop_duplicates()
            .reset_index(drop=True)
        )

    ingredient_summary = (
        recipe_links.merge(ingredient_dimension, on="ingredient_id", how="left")
        .groupby("pizza_type_id")["ingredient_name"]
        .apply(lambda values: ", ".join(values.astype(str)))
        .to_dict()
    )
    normalized_types["ingredients"] = normalized_types["pizza_type_id"].map(ingredient_summary)
    normalized_types["category"] = normalized_types["category_id"].map(
        categories.set_index("category_id")["category_name"]
    )

    catalog_quality = {
        "coluna ingredients disponível na origem": int("ingredients" in types.columns),
        "regras de receita específicas do projeto aplicadas": int(apply_project_recipe_rules),
        "categorias na dimensão categories": int(len(categories)),
        "tipos de pizza na dimensão pizza_types": int(len(normalized_types)),
        "ingredientes únicos na dimensão ingredients": int(len(ingredient_dimension)),
        "relações tipo-ingrediente na tabela associativa": int(len(recipe_links)),
        "ocorrências Artichoke padronizadas para Artichokes": artichoke_standardizations,
        "receitas com Mozzarella Cheese conforme regra do ETL": int(
            recipe_links.merge(ingredient_dimension, on="ingredient_id", how="left")
            .loc[lambda frame: frame["ingredient_name"].eq("Mozzarella Cheese"), "pizza_type_id"]
            .nunique()
        ),
        "receitas com Tomato Sauce conforme regra do ETL": int(
            recipe_links.merge(ingredient_dimension, on="ingredient_id", how="left")
            .loc[lambda frame: frame["ingredient_name"].eq("Tomato Sauce"), "pizza_type_id"]
            .nunique()
        ),
        "combinações tipo-ingrediente duplicadas": int(
            recipe_links.duplicated(subset=["pizza_type_id", "ingredient_id"]).sum()
        ),
    }
    return normalized_types, catalog_quality


def prepare_sales(
    orders: pd.DataFrame,
    details: pd.DataFrame,
    pizzas: pd.DataFrame,
    pizza_types: pd.DataFrame,
    *,
    apply_project_recipe_rules: bool = True,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Valida as tabelas e monta o conjunto de linhas de venda para os gráficos."""
    source_tables = {
        "orders": orders.copy(),
        "order_details": details.copy(),
        "pizzas": pizzas.copy(),
        "pizza_types": pizza_types.copy(),
    }
    for name, dataframe in source_tables.items():
        validate_table(name, dataframe)

    orders = source_tables["orders"]
    details = source_tables["order_details"]
    pizzas = source_tables["pizzas"]
    pizza_types = source_tables["pizza_types"]

    id_columns = [
        (orders, "order_id"),
        (details, "order_id"),
        (details, "pizza_id"),
        (pizzas, "pizza_id"),
        (pizzas, "pizza_type_id"),
        (pizza_types, "pizza_type_id"),
    ]
    if "order_details_id" in details.columns:
        id_columns.append((details, "order_details_id"))
    for dataframe, column in id_columns:
        if dataframe[column].isna().any():
            raise ValueError(f"Há identificadores vazios no campo {column}.")
        dataframe[column] = dataframe[column].astype(str).str.strip()
        if dataframe[column].eq("").any():
            raise ValueError(f"Há identificadores em branco no campo {column}.")

    duplicate_orders = int(orders["order_id"].duplicated().sum())
    duplicate_details = (
        int(details["order_details_id"].duplicated().sum())
        if "order_details_id" in details.columns
        else 0
    )
    duplicate_pizzas = int(pizzas["pizza_id"].duplicated().sum())
    duplicate_types = int(pizza_types["pizza_type_id"].duplicated().sum())
    if duplicate_orders or duplicate_details or duplicate_pizzas or duplicate_types:
        raise ValueError(
            "Há chaves duplicadas nas dimensões: "
            f"orders={duplicate_orders}, order_details={duplicate_details}, "
            f"pizzas={duplicate_pizzas}, tipos={duplicate_types}."
        )

    orders["date"] = pd.to_datetime(orders["date"], errors="coerce").dt.normalize()
    details["quantity"] = pd.to_numeric(details["quantity"], errors="coerce")
    pizzas["price"] = pd.to_numeric(pizzas["price"], errors="coerce")
    pizzas["size"] = pizzas["size"].astype(str).str.strip().str.upper()
    if orders["date"].isna().any():
        raise ValueError("Há datas inválidas ou vazias no arquivo orders.csv.")
    if details["quantity"].isna().any() or (details["quantity"] <= 0).any():
        raise ValueError("quantity deve conter apenas números positivos.")
    if pizzas["price"].isna().any() or (pizzas["price"] <= 0).any():
        raise ValueError("price deve conter apenas números positivos.")
    dates_outside_reference = int(
        (~orders["date"].between("2015-01-01", "2015-12-31")).sum()
    )
    nonstandard_sizes = int((~pizzas["size"].isin(["S", "M", "L", "XL", "XXL"])).sum())
    duplicate_type_names = int(pizza_types["name"].astype(str).str.strip().duplicated().sum())

    order_columns = orders[["order_id", "date", "time"]].copy()
    merged = details.merge(order_columns, on="order_id", how="left", indicator="_order_join")
    missing_orders = int((merged["_order_join"] == "left_only").sum())
    merged = merged.loc[merged["_order_join"] == "both"].drop(columns="_order_join")

    merged = merged.merge(
        pizzas[["pizza_id", "pizza_type_id", "size", "price"]],
        on="pizza_id",
        how="left",
        indicator="_pizza_join",
    )
    missing_pizzas = int((merged["_pizza_join"] == "left_only").sum())
    merged = merged.loc[merged["_pizza_join"] == "both"].drop(columns="_pizza_join")

    normalized_types, catalog_quality = normalize_catalog(
        pizza_types,
        apply_project_recipe_rules=apply_project_recipe_rules,
    )
    merged = merged.merge(
        normalized_types,
        on="pizza_type_id",
        how="left",
        indicator="_type_join",
    )
    missing_types = int((merged["_type_join"] == "left_only").sum())
    merged = merged.loc[merged["_type_join"] == "both"].drop(columns="_type_join")

    merged["order_datetime"] = pd.to_datetime(
        merged["date"].dt.strftime("%Y-%m-%d") + " " + merged["time"].astype(str),
        errors="coerce",
    )
    bad_times = int(merged["order_datetime"].isna().sum())
    merged = merged.dropna(subset=["order_datetime"])
    merged["revenue"] = merged["quantity"] * merged["price"]
    merged["hour"] = merged["order_datetime"].dt.hour
    merged["weekday_num"] = merged["order_datetime"].dt.day_of_week
    merged["weekday"] = pd.Categorical(
        merged["weekday_num"].map(dict(enumerate(DAY_NAMES))),
        categories=DAY_NAMES,
        ordered=True,
    )
    merged["product"] = merged["name"].astype(str) + " - " + merged["size"].astype(str)

    quality = {
        "linhas sem pedido correspondente": missing_orders,
        "linhas sem pizza correspondente": missing_pizzas,
        "linhas sem tipo correspondente": missing_types,
        "linhas com horário inválido": bad_times,
        "order_details_id duplicados (quando informado)": duplicate_details,
        "datas fora do ano da base de referência (2015)": dates_outside_reference,
        "tamanhos fora do padrão do esquema do projeto": nonstandard_sizes,
        "nomes de pizza repetidos no catálogo": duplicate_type_names,
        "tabela orders (registros)": int(len(orders)),
        "tabela order_details (registros)": int(len(details)),
        "tabela pizzas (registros)": int(len(pizzas)),
        "tabela pizza_types (registros)": int(len(pizza_types)),
        **catalog_quality,
    }
    quality["tabela categories (registros)"] = catalog_quality["categorias na dimensão categories"]
    quality["tabela ingredients (registros)"] = catalog_quality["ingredientes únicos na dimensão ingredients"]
    quality["tabela pizza_type_ingredients (registros)"] = catalog_quality[
        "relações tipo-ingrediente na tabela associativa"
    ]
    return merged.reset_index(drop=True), quality


def prepare_normalized_sales(
    orders: pd.DataFrame,
    details: pd.DataFrame,
    pizzas: pd.DataFrame,
    pizza_types: pd.DataFrame,
    categories: pd.DataFrame,
    ingredients: pd.DataFrame,
    recipe_links: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Monta vendas a partir das sete tabelas já normalizadas do projeto."""
    tables = {
        "orders": orders.copy(),
        "order_details": details.copy(),
        "pizzas": pizzas.copy(),
        "pizza_types": pizza_types.copy(),
        "categories": categories.copy(),
        "ingredients": ingredients.copy(),
        "pizza_type_ingredients": recipe_links.copy(),
    }
    required_columns = {
        "orders": {"order_id", "date", "time"},
        "order_details": {"order_details_id", "order_id", "pizza_id", "quantity"},
        "pizzas": {"pizza_id", "pizza_type_id", "size", "price"},
        "pizza_types": {"pizza_type_id", "name", "category_id"},
        "categories": {"category_id", "category_name"},
        "ingredients": {"ingredient_id", "ingredient_name"},
        "pizza_type_ingredients": {"pizza_type_id", "ingredient_id"},
    }
    for table_name, dataframe in tables.items():
        missing = required_columns[table_name].difference(dataframe.columns)
        if missing:
            raise ValueError(
                f"Tabela normalizada {table_name} está sem as colunas: {', '.join(sorted(missing))}."
            )
        if dataframe.empty:
            raise ValueError(f"Tabela normalizada {table_name} não contém registros.")

    string_keys = [
        (tables["orders"], "order_id"),
        (tables["order_details"], "order_id"),
        (tables["order_details"], "pizza_id"),
        (tables["pizzas"], "pizza_id"),
        (tables["pizzas"], "pizza_type_id"),
        (tables["pizza_types"], "pizza_type_id"),
        (tables["pizza_type_ingredients"], "pizza_type_id"),
    ]
    for dataframe, column in string_keys:
        if dataframe[column].isna().any():
            raise ValueError(f"A tabela normalizada contém chave nula em {column}.")
        dataframe[column] = dataframe[column].astype(str).str.strip()

    for table_name, key in [
        ("orders", "order_id"),
        ("order_details", "order_details_id"),
        ("pizzas", "pizza_id"),
        ("pizza_types", "pizza_type_id"),
        ("categories", "category_id"),
        ("ingredients", "ingredient_id"),
    ]:
        if tables[table_name][key].isna().any() or tables[table_name][key].duplicated().any():
            raise ValueError(f"A chave primária {table_name}.{key} está nula ou duplicada.")
    if tables["pizza_type_ingredients"].duplicated(["pizza_type_id", "ingredient_id"]).any():
        raise ValueError("A tabela associativa contém uma relação pizza-ingrediente duplicada.")

    orders = tables["orders"]
    details = tables["order_details"]
    pizzas = tables["pizzas"]
    types = tables["pizza_types"]
    categories = tables["categories"]
    ingredients = tables["ingredients"]
    links = tables["pizza_type_ingredients"]

    orders["date"] = pd.to_datetime(orders["date"], errors="coerce").dt.normalize()
    details["quantity"] = pd.to_numeric(details["quantity"], errors="coerce")
    pizzas["price"] = pd.to_numeric(pizzas["price"], errors="coerce")
    pizzas["size"] = pizzas["size"].astype(str).str.strip().str.upper()
    if orders["date"].isna().any():
        raise ValueError("A tabela normalizada orders contém datas inválidas.")
    if details["quantity"].isna().any() or (details["quantity"] <= 0).any():
        raise ValueError("A tabela normalizada order_details contém quantity inválida.")
    if pizzas["price"].isna().any() or (pizzas["price"] <= 0).any():
        raise ValueError("A tabela normalizada pizzas contém price inválido.")

    order_join = details.merge(
        orders[["order_id", "date", "time"]],
        on="order_id",
        how="left",
        indicator="_order_join",
        validate="many_to_one",
    )
    missing_orders = int(order_join["_order_join"].eq("left_only").sum())
    sales = order_join.loc[order_join["_order_join"].eq("both")].drop(columns="_order_join")
    pizza_join = sales.merge(
        pizzas[["pizza_id", "pizza_type_id", "size", "price"]],
        on="pizza_id",
        how="left",
        indicator="_pizza_join",
        validate="many_to_one",
    )
    missing_pizzas = int(pizza_join["_pizza_join"].eq("left_only").sum())
    sales = pizza_join.loc[pizza_join["_pizza_join"].eq("both")].drop(columns="_pizza_join")
    type_join = sales.merge(
        types[["pizza_type_id", "name", "category_id"]],
        on="pizza_type_id",
        how="left",
        indicator="_type_join",
        validate="many_to_one",
    )
    missing_types = int(type_join["_type_join"].eq("left_only").sum())
    sales = type_join.loc[type_join["_type_join"].eq("both")].drop(columns="_type_join")
    category_join = sales.merge(
        categories[["category_id", "category_name"]],
        on="category_id",
        how="left",
        indicator="_category_join",
        validate="many_to_one",
    )
    missing_categories = int(category_join["_category_join"].eq("left_only").sum())
    sales = category_join.loc[category_join["_category_join"].eq("both")].drop(columns="_category_join")
    sales = sales.rename(columns={"category_name": "category"})

    normalized_recipe = links.merge(
        ingredients[["ingredient_id", "ingredient_name"]],
        on="ingredient_id",
        how="left",
        indicator="_ingredient_join",
        validate="many_to_one",
    )
    missing_ingredients = int(normalized_recipe["_ingredient_join"].eq("left_only").sum())
    normalized_recipe = normalized_recipe.loc[
        normalized_recipe["_ingredient_join"].eq("both"), ["pizza_type_id", "ingredient_name"]
    ]
    ingredient_map = (
        normalized_recipe.groupby("pizza_type_id")["ingredient_name"]
        .apply(lambda values: ", ".join(values.astype(str)))
        .to_dict()
    )
    sales["ingredients"] = sales["pizza_type_id"].map(ingredient_map)

    sales["order_datetime"] = pd.to_datetime(
        sales["date"].dt.strftime("%Y-%m-%d") + " " + sales["time"].astype(str),
        errors="coerce",
    )
    bad_times = int(sales["order_datetime"].isna().sum())
    sales = sales.dropna(subset=["order_datetime"])
    sales["revenue"] = sales["quantity"] * sales["price"]
    sales["hour"] = sales["order_datetime"].dt.hour
    sales["weekday_num"] = sales["order_datetime"].dt.day_of_week
    sales["weekday"] = pd.Categorical(
        sales["weekday_num"].map(dict(enumerate(DAY_NAMES))),
        categories=DAY_NAMES,
        ordered=True,
    )
    sales["product"] = sales["name"].astype(str) + " - " + sales["size"].astype(str)

    quality = {
        "linhas sem pedido correspondente": missing_orders,
        "linhas sem pizza correspondente": missing_pizzas,
        "linhas sem tipo correspondente": missing_types,
        "linhas sem categoria correspondente": missing_categories,
        "relações sem ingrediente correspondente": missing_ingredients,
        "linhas com horário inválido": bad_times,
        "tabela orders (registros)": int(len(orders)),
        "tabela order_details (registros)": int(len(details)),
        "tabela pizzas (registros)": int(len(pizzas)),
        "tabela pizza_types (registros)": int(len(types)),
        "tabela categories (registros)": int(len(categories)),
        "tabela ingredients (registros)": int(len(ingredients)),
        "tabela pizza_type_ingredients (registros)": int(len(links)),
        "regras de normalização consumidas": 1,
    }
    return sales.reset_index(drop=True), quality


def load_project_normalized_csvs() -> tuple[pd.DataFrame, dict[str, int]]:
    """Lê diretamente os arquivos das sete tabelas resultantes do ETL normalizado."""
    table_names = [
        "orders",
        "order_details",
        "pizzas",
        "pizza_types",
        "categories",
        "ingredients",
        "pizza_type_ingredients",
    ]
    missing = [name for name in table_names if not (NORMALIZED_DATA_DIR / f"{name}.csv").exists()]
    if missing:
        raise FileNotFoundError(
            "A camada normalizada não foi encontrada. Gere-a sem alterar os CSVs de origem com "
            "`python src/04_exportar_base_normalizada.py`. Tabelas ausentes: "
            + ", ".join(missing)
        )
    tables = {
        name: read_csv_path(NORMALIZED_DATA_DIR / f"{name}.csv")
        for name in table_names
    }
    return prepare_normalized_sales(
        tables["orders"],
        tables["order_details"],
        tables["pizzas"],
        tables["pizza_types"],
        tables["categories"],
        tables["ingredients"],
        tables["pizza_type_ingredients"],
    )


def load_sql_server(database_url: str) -> tuple[pd.DataFrame, dict[str, int]]:
    """Lê o esquema normalizado com SELECTs; não altera o banco."""
    sales_query = text(
        """
        SELECT o.order_id, o.[date], o.[time], od.pizza_id, od.quantity,
               p.pizza_type_id, p.size, p.price, pt.name, c.category_name AS category
        FROM orders AS o
        INNER JOIN order_details AS od ON od.order_id = o.order_id
        INNER JOIN pizzas AS p ON p.pizza_id = od.pizza_id
        INNER JOIN pizza_types AS pt ON pt.pizza_type_id = p.pizza_type_id
        INNER JOIN categories AS c ON c.category_id = pt.category_id
        ORDER BY o.[date], o.[time]
        """
    )
    ingredients_query = text(
        """
        SELECT pti.pizza_type_id, i.ingredient_name
        FROM pizza_type_ingredients AS pti
        INNER JOIN ingredients AS i ON i.ingredient_id = pti.ingredient_id
        ORDER BY pti.pizza_type_id, i.ingredient_name
        """
    )
    counts_query = text(
        """
        SELECT
            (SELECT COUNT(*) FROM orders) AS orders_count,
            (SELECT COUNT(*) FROM order_details) AS order_details_count,
            (SELECT COUNT(*) FROM pizzas) AS pizzas_count,
            (SELECT COUNT(*) FROM pizza_types) AS pizza_types_count,
            (SELECT COUNT(*) FROM categories) AS categories_count,
            (SELECT COUNT(*) FROM ingredients) AS ingredients_count,
            (SELECT COUNT(*) FROM pizza_type_ingredients) AS recipe_links_count
        """
    )
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            sales = pd.read_sql(sales_query, connection)
            ingredients = pd.read_sql(ingredients_query, connection)
            table_counts = pd.read_sql(counts_query, connection).iloc[0].to_dict()
    finally:
        engine.dispose()

    ingredient_map = (
        ingredients.groupby("pizza_type_id")["ingredient_name"]
        .apply(lambda values: ", ".join(values.astype(str)))
        .to_dict()
    )
    sales["ingredients"] = sales["pizza_type_id"].map(ingredient_map)
    sales["order_id"] = sales["order_id"].astype(str)
    sales["pizza_id"] = sales["pizza_id"].astype(str)
    sales["pizza_type_id"] = sales["pizza_type_id"].astype(str)
    sales["date"] = pd.to_datetime(sales["date"], errors="coerce").dt.normalize()
    sales["order_datetime"] = pd.to_datetime(
        sales["date"].dt.strftime("%Y-%m-%d") + " " + sales["time"].astype(str),
        errors="coerce",
    )
    sales["quantity"] = pd.to_numeric(sales["quantity"], errors="coerce")
    sales["price"] = pd.to_numeric(sales["price"], errors="coerce")
    sales = sales.dropna(subset=["order_datetime", "quantity", "price"])
    sales["revenue"] = sales["quantity"] * sales["price"]
    sales["hour"] = sales["order_datetime"].dt.hour
    sales["weekday_num"] = sales["order_datetime"].dt.day_of_week
    sales["weekday"] = pd.Categorical(
        sales["weekday_num"].map(dict(enumerate(DAY_NAMES))),
        categories=DAY_NAMES,
        ordered=True,
    )
    sales["product"] = sales["name"].astype(str) + " - " + sales["size"].astype(str)
    quality = {
        "linhas sem pedido correspondente": 0,
        "linhas sem pizza correspondente": 0,
        "linhas sem tipo correspondente": 0,
        "linhas com horário inválido": 0,
    }
    quality.update(
        {
            f"tabela {table_name} (registros)": int(table_counts[count_column])
            for table_name, count_column in [
                ("orders", "orders_count"),
                ("order_details", "order_details_count"),
                ("pizzas", "pizzas_count"),
                ("pizza_types", "pizza_types_count"),
                ("categories", "categories_count"),
                ("ingredients", "ingredients_count"),
                ("pizza_type_ingredients", "recipe_links_count"),
            ]
        }
    )
    quality["regras de normalização consumidas"] = 1
    return sales.reset_index(drop=True), quality


def load_uploaded_csvs(
    uploaded: dict[str, object],
    *,
    apply_project_recipe_rules: bool,
) -> tuple[pd.DataFrame, dict[str, int]]:
    orders = read_uploaded_csv(uploaded["orders"])
    details = read_uploaded_csv(uploaded["order_details"])
    pizzas = read_uploaded_csv(uploaded["pizzas"])
    pizza_types = read_uploaded_csv(uploaded["pizza_types"], latin1_fallback=True)
    return prepare_sales(
        orders,
        details,
        pizzas,
        pizza_types,
        apply_project_recipe_rules=apply_project_recipe_rules,
    )


def load_analysis_queries(path: Path = ANALYSIS_QUERIES_PATH) -> list[dict[str, str]]:
    """Separa o arquivo de consultas em blocos numerados (por exemplo, 1.1 e 6.4)."""
    sql_text = path.read_text(encoding="utf-8-sig")
    markers = list(QUERY_MARKER.finditer(sql_text))
    queries = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(sql_text)
        query_text = sql_text[marker.end():end].strip()
        if query_text:
            queries.append(
                {
                    "number": marker.group(1),
                    "title": marker.group(2).strip(),
                    "sql": query_text,
                }
            )
    if not queries:
        raise ValueError("Nenhuma consulta numerada foi encontrada em 03_analysis_queries.sql.")
    return queries


def adapt_sqlite_query(query: str) -> str:
    """Converte TOP N para LIMIT e adapta os JOINs das consultas do arquivo ao SQLite."""
    top_match = re.search(r"\bSELECT\s+TOP\s+(\d+)\s+", query, flags=re.IGNORECASE)
    limit = int(top_match.group(1)) if top_match else None
    if top_match:
        query = query[:top_match.start()] + "SELECT " + query[top_match.end():]

    # RIGHT/FULL OUTER JOIN só existem em versões recentes do SQLite.
    # Estas consultas fixas são reescritas como LEFT JOIN para compatibilidade com versões antigas do WSL.
    normalized_query = re.sub(r"\s+", " ", query).strip().rstrip(";")
    if re.search(
        r"\bRIGHT\s+JOIN\s+categories\s+c\s+ON\s+pt\.category_id\s*=\s*c\.category_id\b",
        normalized_query,
        re.IGNORECASE,
    ):
        query = re.sub(
            r"FROM\s+pizza_types\s+pt\s+RIGHT\s+JOIN\s+categories\s+c\s+ON\s+pt\.category_id\s*=\s*c\.category_id",
            "FROM categories c LEFT JOIN pizza_types pt ON pt.category_id = c.category_id",
            query,
            flags=re.IGNORECASE,
        )
    elif re.search(r"\bFULL\s+OUTER\s+JOIN\s+pizza_types\s+pt\b", normalized_query, re.IGNORECASE):
        query = """
SELECT p.pizza_id, pt.name
FROM pizzas p
LEFT JOIN pizza_types pt ON p.pizza_type_id = pt.pizza_type_id
WHERE p.pizza_id IS NOT NULL AND pt.pizza_type_id IS NULL
UNION ALL
SELECT p.pizza_id, pt.name
FROM pizza_types pt
LEFT JOIN pizzas p ON p.pizza_type_id = pt.pizza_type_id
WHERE p.pizza_id IS NULL
"""

    query = query.strip().rstrip(";").strip()
    if limit is not None:
        query += f"\nLIMIT {limit}"
    return query


def execute_sqlite_analysis_query(query: str) -> pd.DataFrame:
    """Carrega as sete tabelas normalizadas em SQLite em memória e executa a consulta."""
    missing = [
        table for table in NORMALIZED_TABLES
        if not (NORMALIZED_DATA_DIR / f"{table}.csv").is_file()
    ]
    if missing:
        raise FileNotFoundError(
            "A camada normalizada está incompleta. Gere os CSVs com `make normalize`. "
            "Tabelas ausentes: " + ", ".join(missing)
        )

    signature = tuple(
        (
            table,
            (NORMALIZED_DATA_DIR / f"{table}.csv").stat().st_mtime_ns,
            (NORMALIZED_DATA_DIR / f"{table}.csv").stat().st_size,
        )
        for table in NORMALIZED_TABLES
    )
    return _execute_sqlite_analysis_query_cached(query, signature)


@st.cache_data(show_spinner=False, max_entries=64)
def _execute_sqlite_analysis_query_cached(
    query: str,
    signature: tuple[tuple[str, int, int], ...],
) -> pd.DataFrame:
    # A assinatura invalida o cache quando make normalize atualiza qualquer tabela.
    with sqlite3.connect(":memory:") as connection:
        for table in NORMALIZED_TABLES:
            dataframe = read_csv_path(NORMALIZED_DATA_DIR / f"{table}.csv")
            dataframe.to_sql(table, connection, index=False, if_exists="replace")
        return pd.read_sql_query(adapt_sqlite_query(query), connection)


def sql_server_has_normalized_schema(database_url: str) -> bool:
    """Confirma que o banco configurado contém as sete tabelas normalizadas do projeto."""
    engine = None
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            for table in NORMALIZED_TABLES:
                connection.execute(text(f"SELECT TOP 0 * FROM dbo.{table}"))
        return True
    except Exception:
        return False
    finally:
        if engine is not None:
            engine.dispose()


def execute_analysis_query(
    query: str,
    *,
    database_url: str = "",
    require_sql_server: bool = False,
) -> tuple[pd.DataFrame, str]:
    """Usa SQL Server se solicitado ou disponível; caso contrário usa SQLite local."""
    if require_sql_server:
        if not database_url:
            raise ValueError("Configure PIZZA_DATABASE_URL para executar consultas no SQL Server.")
        engine = create_engine(database_url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                return pd.read_sql(text(query), connection), "SQL Server · PizzaSales"
        finally:
            engine.dispose()

    if database_url and sql_server_has_normalized_schema(database_url):
        engine = create_engine(database_url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                return pd.read_sql(text(query), connection), "SQL Server · PizzaSales"
        finally:
            engine.dispose()

    return execute_sqlite_analysis_query(query), "SQLite em memória · data/normalized/"


def load_forecast_module():
    spec = importlib.util.spec_from_file_location("pizza_demand_model", MODEL_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Não foi possível carregar o modelo em {MODEL_PATH}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def format_number(value: float, decimals: int = 0) -> str:
    formatted = f"{value:,.{decimals}f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def format_money(value: float, symbol: str) -> str:
    amount = format_number(value, 2)
    return f"{symbol} {amount}" if symbol else amount


def format_compact_money(value: float, symbol: str) -> str:
    """Encurta valores grandes para caber nos cartões do painel."""
    if abs(value) >= 1_000_000:
        amount = f"{format_number(value / 1_000_000, 1)} mi"
    elif abs(value) >= 1_000:
        amount = f"{format_number(value / 1_000, 1)} mil"
    else:
        amount = format_number(value, 2)
    return f"{symbol} {amount}" if symbol else amount


def render_csv_preparation_guide(widget_key: str) -> None:
    """Plain-language CSV guide shown before a user imports an external file."""
    with st.expander("Antes de enviar seu CSV", expanded=True):
        st.warning(
            "Um mesmo pedido pode aparecer em várias linhas quando contém diferentes produtos. "
            "Isso é permitido e não representa duplicidade. O sistema sinaliza registros aparentemente "
            "duplicados para conferência, mas não exclui vendas automaticamente."
        )
        st.markdown(
            "Cada linha representa um item vendido. Informe a quantidade de unidades daquele item e repita "
            "o `pedido_id` nas linhas que pertencem ao mesmo pedido. Os valores de exemplo abaixo são genéricos; "
            "use o cardápio e os códigos do seu estabelecimento."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {"Coluna": "data", "Regra": "AAAA-MM-DD; datas brasileiras somente quando reconhecíveis sem ambiguidade.", "Obrigatoriedade": "Obrigatória"},
                    {"Coluna": "quantidade", "Regra": "Número inteiro positivo de unidades por linha.", "Obrigatoriedade": "Obrigatória"},
                    {"Coluna": "pedido_id", "Regra": "Identificador como texto; pode se repetir entre itens do pedido.", "Obrigatoriedade": "Necessária para KPIs por pedido"},
                    {"Coluna": "hora", "Regra": "HH ou HH:MM, como 18 ou 18:30.", "Obrigatoriedade": "Recomendada"},
                    {"Coluna": "produto", "Regra": "Nome sem incorporar o tamanho.", "Obrigatoriedade": "Recomendada para produtos"},
                    {"Coluna": "tamanho", "Regra": "Tamanho próprio do estabelecimento; não há lista fixa.", "Obrigatoriedade": "Recomendada"},
                    {"Coluna": "preco_unitario", "Regra": "Preço cobrado por unidade, sem símbolo de moeda; 35.90 ou 35,90.", "Obrigatoriedade": "Necessária para faturamento"},
                    {"Coluna": "categoria", "Regra": "Categoria usada pela pizzaria.", "Obrigatoriedade": "Recomendada"},
                    {"Coluna": "ingredientes", "Regra": "Lista separada por vírgula ou ponto e vírgula.", "Obrigatoriedade": "Opcional"},
                ]
            ),
            hide_index=True,
            width="stretch",
        )
        st.markdown("**Exemplos de linhas**")
        st.code(
            "data,quantidade,pedido_id,hora,produto,tamanho,preco_unitario,categoria,ingredientes\n"
            "2026-01-15,2,1001,18:30,Calabresa,M,35.90,Tradicional,\"Molho; queijo; calabresa\"\n"
            "2026-01-15,1,1001,18:30,Margherita,M,32.00,Vegetariana,\"Molho; queijo; tomate\"\n"
            "2026-01-15,1,1002,19:15,Nutella,G,65.00,Doce,\"Creme de avelã\"",
            language="csv",
        )
        st.caption(
            "As duas primeiras linhas formam um pedido com produtos diferentes. O mesmo produto em pedidos "
            "diferentes também é normal. Linhas idênticas são apenas possíveis duplicidades e precisam de conferência."
        )
        st.markdown("**Mesmo produto em pedidos diferentes — registros válidos**")
        st.code(
            "2026-01-15,2,1001,18:30,Calabresa,M,35.90,Tradicional,\"Molho; queijo; calabresa\"\n"
            "2026-01-15,2,1002,19:10,Calabresa,M,35.90,Tradicional,\"Molho; queijo; calabresa\"",
            language="csv",
        )
        st.markdown("**Possível duplicidade — sinalizada, não excluída**")
        st.code(
            "2026-01-15,2,1001,18:30,Calabresa,M,35.90,Tradicional,\"Molho; queijo; calabresa\"\n"
            "2026-01-15,2,1001,18:30,Calabresa,M,35.90,Tradicional,\"Molho; queijo; calabresa\"",
            language="csv",
        )
        st.caption(
            "O painel não sabe se uma repetição exata é erro de exportação ou duas operações legítimas. "
            "A conferência e qualquer correção ficam a cargo do responsável pela pizzaria."
        )
        st.download_button(
            "Baixar modelo de CSV",
            data=CSV_TEMPLATE_PATH.read_bytes(),
            file_name="modelo_csv_vendas_pizzaria.csv",
            mime="text/csv",
            key=f"download_template_guide_{widget_key}",
        )
        st.markdown(
            "Dias fechados recebem zero somente na série temporal. Um dia aberto sem registro fica como "
            "desconhecido até você confirmar que não houve vendas. Essa confirmação não cria uma linha de pedido."
        )


def render_external_csv_wizard(uploaded_file):
    """Validate a user CSV, keep its bytes intact, and return only an acknowledged analysis view."""
    file_bytes = uploaded_file.getvalue()
    file_name = getattr(uploaded_file, "name", "vendas.csv")
    file_key = hashlib.sha256(file_bytes).hexdigest()[:12]
    display_default = Path(file_name).stem

    st.subheader("Validação e diagnóstico dos dados")
    parsed = parse_sales_csv(file_bytes)
    suggestions, candidates = suggest_column_mapping(parsed.headers)
    mapping: dict[str, str | None] = {}

    if parsed.headers:
        st.markdown(
            "O painel encontrou as colunas abaixo. Revise cada associação; nomes equivalentes são sugestões, "
            "e não são aplicados antes da sua confirmação."
        )
        mapping_preview = pd.DataFrame(
            [
                {
                    "Campo do painel": column,
                    "Sugestão": suggestions.get(column) or "—",
                    "Colunas candidatas": ", ".join(candidates.get(column, [])) or "—",
                    "Uso": "Obrigatório" if column in ("data", "quantidade") else "Opcional ou habilita uma análise",
                }
                for column in IMPORT_COLUMNS
            ]
        )
        st.dataframe(mapping_preview, hide_index=True, width="stretch")
        with st.expander("Revisar ou alterar o mapeamento", expanded=True):
            options = ["— não mapear —", *parsed.headers]
            left, right = st.columns(2)
            for position, column in enumerate(IMPORT_COLUMNS):
                selected_suggestion = suggestions.get(column)
                default_index = options.index(selected_suggestion) if selected_suggestion in options else 0
                target_column = left if position % 2 == 0 else right
                with target_column:
                    selected = st.selectbox(
                        f"Coluna do CSV para {column}",
                        options,
                        index=default_index,
                        key=f"csv_map_{file_key}_{column}",
                    )
                mapping[column] = None if selected == options[0] else selected
            mapping_confirmed = st.checkbox(
                "Revisei e confirmo o mapeamento mostrado acima",
                key=f"csv_mapping_confirm_{file_key}",
            )
    else:
        mapping_confirmed = False
        mapping = {column: None for column in IMPORT_COLUMNS}
        st.error("O arquivo está vazio ou não tem um cabeçalho que possa ser lido.")

    establishment_name = st.text_input(
        "Nome ou identificação do estabelecimento (opcional)",
        value=display_default,
        key=f"csv_establishment_{file_key}",
    ).strip() or display_default
    order_identity_label = st.radio(
        "Como o caixa identifica um pedido?",
        ["pedido_id é único globalmente", "o número do pedido reinicia a cada data"],
        help=(
            "A primeira opção conta cada pedido_id uma vez no arquivo. A segunda conta a combinação data + pedido_id, "
            "útil quando o caixa reutiliza números em dias diferentes. O identificador original continua preservado."
        ),
        key=f"csv_order_identity_{file_key}",
    )
    order_identity = "date_order" if order_identity_label.startswith("o número") else "global"

    with st.expander("Configuração do estabelecimento: dias e horários", expanded=True):
        st.caption(
            "Os horários abaixo são valores iniciais editáveis, não regras aplicadas ao seu negócio. "
            "Revise cada dia e confirme a configuração."
        )
        schedule_defaults = pd.DataFrame(
            {
                "Dia": DAY_NAMES,
                "Abre?": [True] * 7,
                "Abertura": ["18:00"] * 7,
                "Fechamento": ["23:00"] * 7,
            }
        )
        schedule_editor = st.data_editor(
            schedule_defaults,
            hide_index=True,
            width="stretch",
            key=f"csv_schedule_{file_key}",
            column_config={
                "Dia": st.column_config.TextColumn(disabled=True),
                "Abre?": st.column_config.CheckboxColumn(help="Desmarque se a pizzaria fica fechada neste dia."),
                "Abertura": st.column_config.TextColumn(help="Formato HH:MM, como 18:00."),
                "Fechamento": st.column_config.TextColumn(help="Formato HH:MM, como 23:00."),
            },
        )
        calendar_confirmed = st.checkbox(
            "Revisei e confirmo os dias e horários de funcionamento",
            key=f"csv_calendar_confirm_{file_key}",
        )

    schedule = schedule_from_rows(schedule_editor.to_dict("records"))
    provisional = validate_sales_csv(
        parsed,
        mapping,
        order_identity=order_identity,
        schedule=schedule,
        schedule_confirmed=calendar_confirmed,
        confirm_open_no_sales=False,
    )
    open_gaps = (
        not provisional.issues.empty
        and provisional.issues["Mensagem"].astype(str).str.contains("Dia configurado como aberto sem registro", regex=False).any()
    )
    confirm_open_zero = False
    if open_gaps:
        confirm_open_zero = st.checkbox(
            "Confirmo que os dias abertos sem registro no período selecionado tiveram zero vendas",
            help="Essa confirmação completa somente a série temporal; não adiciona pedidos ao CSV.",
            key=f"csv_open_zero_confirm_{file_key}",
        )

    result = validate_sales_csv(
        parsed,
        mapping,
        order_identity=order_identity,
        schedule=schedule,
        schedule_confirmed=calendar_confirmed,
        confirm_open_no_sales=confirm_open_zero,
    )
    st.markdown(f"**Resultado:** {result.status}")
    summary = result.summary
    date_start = summary["date_start"].strftime("%d/%m/%Y") if summary["date_start"] is not None else "—"
    date_end = summary["date_end"].strftime("%d/%m/%Y") if summary["date_end"] is not None else "—"
    summary_columns = st.columns(4)
    summary_columns[0].metric("Linhas recebidas", summary["total_rows"])
    summary_columns[1].metric("Linhas aptas para análise", summary["valid_analysis_rows"])
    summary_columns[2].metric("Pedidos identificados", summary["distinct_orders"])
    summary_columns[3].metric("Possíveis grupos duplicados", summary["duplicate_groups"])
    st.caption(
        f"Período identificado: {date_start} a {date_end} · unidades nas linhas válidas: {summary['units']} · "
        f"produtos: {summary['products']} · categorias: {summary['categories']} · tamanhos: "
        f"{', '.join(summary['sizes']) if summary['sizes'] else 'não informados'} · dias abertos sem confirmação: {summary['unknown_days']}."
    )

    if not result.issues.empty:
        for level, heading in (("Erro", "Erros"), ("Aviso", "Avisos"), ("Informação", "Informações")):
            selected_issues = result.issues.loc[result.issues["Tipo"].eq(level)]
            if not selected_issues.empty:
                with st.expander(f"{heading} ({len(selected_issues)})", expanded=(level == "Erro")):
                    st.dataframe(selected_issues, hide_index=True, width="stretch")
    else:
        st.success("Não foram encontradas inconsistências nos campos analisados.")

    if summary["duplicate_affected_rows"]:
        st.warning(
            f"Foram identificados {summary['duplicate_groups']} grupo(s) com possíveis duplicidades, "
            f"abrangendo {summary['duplicate_affected_rows']} linha(s). Todas continuam incluídas; confira antes de confirmar."
        )
        st.dataframe(result.duplicate_rows, hide_index=True, width="stretch")

    def has_import_value(column: str) -> bool:
        if column not in result.analysis_frame.columns:
            return False
        values = result.analysis_frame[column].astype("string").fillna("").str.strip()
        return bool(values.ne("").any())

    capability_rows = [
        {"Análise": "Volume diário", "Situação": "Disponível" if result.mapping_ready and not result.analysis_frame.empty else "Indisponível: confira data e quantidade"},
        {"Análise": "Pedidos / ticket / unidades por pedido", "Situação": "Disponível" if mapping.get("pedido_id") is not None and summary["missing_order_id_rows"] == 0 else "Indisponível ou incompleto: pedido_id ausente/incompleto"},
        {"Análise": "Faturamento bruto", "Situação": "Disponível" if result.revenue_available else "Indisponível: preço inválido, ausente ou incompleto"},
        {"Análise": "Produtos", "Situação": "Disponível" if has_import_value("produto") else "Indisponível: inclua produto"},
        {"Análise": "Categorias", "Situação": "Disponível" if has_import_value("categoria") else "Indisponível: inclua categoria"},
        {"Análise": "Tamanhos", "Situação": "Disponível" if has_import_value("tamanho") else "Indisponível: inclua tamanho"},
        {"Análise": "Horários", "Situação": "Disponível" if has_import_value("hora") else "Indisponível: inclua hora"},
        {"Análise": "Ingredientes", "Situação": "Disponível" if has_import_value("ingredientes") else "Indisponível: inclua ingredientes"},
    ]
    with st.expander("Análises compatíveis com este arquivo", expanded=True):
        st.dataframe(pd.DataFrame(capability_rows), hide_index=True, width="stretch")

    report_frame = result.issues if not result.issues.empty else pd.DataFrame(columns=[
        "Número da linha original", "Coluna", "Valor encontrado", "Tipo", "Mensagem", "Ação recomendada"
    ])
    st.download_button(
        "Baixar relatório de validação",
        data=report_frame.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"relatorio_validacao_{file_key}.csv",
        mime="text/csv",
        key=f"csv_validation_report_{file_key}",
    )
    st.download_button(
        "Baixar CSV original sem alterações",
        data=file_bytes,
        file_name=Path(file_name).name,
        mime="text/csv",
        key=f"csv_original_download_{file_key}",
    )
    st.caption(
        "O CSV original permanece intacto. Linhas com data ou quantidade inválidas não entram nos cálculos que dependem "
        "desses campos; linhas aparentemente duplicadas não são eliminadas."
    )

    if not mapping_confirmed:
        st.info("Confirme o mapeamento após revisá-lo para continuar.")
        st.stop()
    if not result.mapping_ready:
        st.error("Mapeie data e quantidade para liberar análises de vendas.")
        st.stop()
    if result.analysis_frame.empty:
        st.error("Não há linhas com data e quantidade válidas para analisar.")
        st.stop()
    import_confirmed = st.checkbox(
        "Revisei o diagnóstico e confirmo a análise. O CSV original e todas as suas linhas serão preservados.",
        key=f"csv_import_confirm_{file_key}",
    )
    if not import_confirmed:
        st.info("Após revisar o diagnóstico, confirme para abrir as análises.")
        st.stop()

    analysis_frame = result.analysis_frame.copy()
    if not result.revenue_available and "preco_unitario" in analysis_frame:
        analysis_frame["preco_unitario"] = ""
    serialized = analysis_frame.to_csv(index=False, date_format="%Y-%m-%d").encode("utf-8-sig")
    sales, quality = prepare_simple_sales(io.BytesIO(serialized))
    # Keep product names separate from size for this generic import route.
    if "produto" in analysis_frame:
        sales["product"] = analysis_frame["produto"].astype("string").replace("", pd.NA).reset_index(drop=True)
    if "order_id" in sales:
        order_ids = sales["order_id"].astype("string").str.strip().replace("", pd.NA)
        if order_identity == "date_order":
            sales["order_key"] = [
                f"{date}|{order_id}" if pd.notna(order_id) else pd.NA
                for date, order_id in zip(sales["date"].dt.strftime("%Y-%m-%d"), order_ids)
            ]
        else:
            sales["order_key"] = order_ids
    quality.update(
        {
            "linhas comerciais válidas": int(len(sales)),
            "linhas da origem preservadas": int(summary["total_rows"]),
            "linhas com erros de data": int(summary["invalid_date_rows"]),
            "linhas com erros de quantidade": int(summary["invalid_quantity_rows"]),
            "grupos com possíveis duplicidades (mantidos)": int(summary["duplicate_groups"]),
            "identidade do pedido": "data + pedido_id" if order_identity == "date_order" else "pedido_id global",
            "calendário confirmado": int(calendar_confirmed),
            "previsão liberada pela validação do calendário": int(result.forecast_ready),
        }
    )
    source_label = f"CSV externo · {establishment_name} · {file_name}"
    return sales, quality, result, source_label


def main() -> None:
    st.title("🍕 Painel de Análise de Dados para Pizzarias")
    st.caption("Projeto Integrador IV · UNIVESP | Python, SQL e Streamlit")
    st.markdown(
        "Ferramenta interativa para explorar vendas, identificar padrões de consumo, "
        "acompanhar indicadores comerciais e apoiar decisões de negócio. O projeto começou "
        "com uma base pública de vendas de pizzaria e foi ampliado para analisar dados de "
        "outros estabelecimentos por meio de arquivos CSV."
    )
    mode_public_card, mode_external_card = st.columns(2)
    with mode_public_card:
        with st.container(border=True):
            st.caption("BASE ORIGINAL DO PROJETO")
            st.subheader("Base pública")
            st.write(
                "Conjunto Pizza Place Sales, usado no desenvolvimento da modelagem relacional, "
                "do ETL, das consultas SQL e das análises originais."
            )
    with mode_external_card:
        with st.container(border=True):
            st.caption("ANÁLISE PERSONALIZADA")
            st.subheader("Dados de outras pizzarias")
            st.write(
                "Carregue um CSV com as vendas do estabelecimento. O arquivo "
                "`VENDAS_PIZZARIA_BAIRRO` é o estudo de caso anonimizado usado para demonstrar essa extensão."
            )

    with st.sidebar:
        st.header("Dados e filtros")
        source = st.radio(
            "Fonte dos dados",
            [
                MODE_PUBLIC,
                MODE_CASE_STUDY,
                MODE_CUSTOM_CSV,
                MODE_FOUR_CSVS,
                MODE_SQL_SERVER,
            ],
        )
        if source == MODE_CASE_STUDY and not CASE_STUDY_CSV_PATH.is_file():
            st.warning(
                "O CSV local do estudo de caso não está disponível neste clone. "
                "As análises continuam usando a base pública; coloque o arquivo autorizado "
                "em output/VENDAS_PIZZARIA_BAIRRO.csv para habilitar o estudo de caso."
            )
            source = MODE_PUBLIC
        uploaded: dict[str, object] = {}
        single_csv = None
        database_url = ""
        apply_project_recipe_rules = True
        closed_weekday_labels = []
        if source == MODE_PUBLIC:
            st.caption("Carrega as sete tabelas exportadas pelo ETL em data/normalized/.")
        if source == MODE_CASE_STUDY:
            st.caption(
                "Estudo de caso com identificação do estabelecimento omitida. "
                "Fonte: output/VENDAS_PIZZARIA_BAIRRO.csv."
            )
            closed_weekday_labels = st.multiselect(
                "Dias sem funcionamento",
                DAY_NAMES,
                default=[DAY_NAMES[0]],
                help="O estudo de caso registra a segunda-feira como dia fechado. Isso afeta somente a série temporal.",
            )
        if source == MODE_CUSTOM_CSV:
            st.caption(
                "Importação guiada: revise o mapeamento, o calendário e o diagnóstico antes de liberar as análises."
            )
            single_csv = st.file_uploader(
                "CSV de vendas",
                type=["csv"],
                key="upload_single_sales_csv",
            )
            st.caption(
                "O estabelecimento define seu cardápio, moeda, dias e horários; nenhuma regra do estudo de caso é aplicada aqui."
            )
        if source == MODE_FOUR_CSVS:
            st.caption("Envie as quatro tabelas do sistema de vendas. Os campos mínimos estão no manual do painel.")
            for key, label in [
                ("orders", "orders.csv — pedidos"),
                ("order_details", "order_details.csv — itens e quantidades"),
                ("pizzas", "pizzas.csv — tamanho e preço"),
                ("pizza_types", "pizza_types.csv — sabores e categorias"),
            ]:
                uploaded_file = st.file_uploader(label, type=["csv"], key=f"upload_{key}")
                if uploaded_file is not None:
                    uploaded[key] = uploaded_file
            apply_project_recipe_rules = st.checkbox(
                "Aplicar regras de receita do ETL deste projeto",
                value=True,
                help=(
                    "Adiciona Mozzarella Cheese a todas as receitas e Tomato Sauce às receitas "
                    "sem outro molho. Desmarque se essas regras não representarem o cardápio da pizzaria."
                ),
            )
            closed_weekday_labels = st.multiselect(
                "Dias sem funcionamento (opcional)",
                DAY_NAMES,
                default=[],
            )
        elif source == MODE_SQL_SERVER:
            database_url = os.environ.get("PIZZA_DATABASE_URL", "").strip()
            st.caption("Conexão somente para leitura. Configure PIZZA_DATABASE_URL no ambiente antes de iniciar o app.")
            if database_url:
                st.info(
                    "PIZZA_DATABASE_URL está configurada; a conexão só é confirmada ao carregar. "
                    "Se SQL Server/ODBC não estiver disponível, o painel usa a base local."
                )
            else:
                st.info("Sem URL configurada. Veja o manual do painel para conectar ao banco PizzaSales.")

        symbol_options = ["US$", "R$", "Sem símbolo"]
        currency_label = st.selectbox(
            "Símbolo da moeda exibida (sem conversão)",
            symbol_options,
            index=0 if source in (MODE_PUBLIC, MODE_SQL_SERVER) else 1,
        )
        currency_symbol = "" if currency_label == "Sem símbolo" else currency_label

        st.divider()
        st.markdown("**Projeto Integrador IV**")
        st.caption("Polo CEU Anhanguera · Polo CEU Carrão")
        st.caption("Orientador: Vinícius Alexandre Ramos Simão")

    if source == MODE_CUSTOM_CSV:
        render_csv_preparation_guide("before_upload")
        if single_csv is None:
            st.info("Baixe o modelo se precisar e envie seu arquivo CSV para iniciar a validação.")
            st.stop()

    custom_import_result = None
    try:
        sql_connected = False
        sql_fallback_message = None
        if source == MODE_PUBLIC:
            sales, quality = load_project_normalized_csvs()
            source_label = "base pública original Pizza Place Sales · camada normalizada em data/normalized/"
        elif source == MODE_CASE_STUDY:
            if not CASE_STUDY_CSV_PATH.exists():
                st.error(f"O CSV do estudo de caso não foi encontrado: {CASE_STUDY_CSV_PATH}")
                st.stop()
            case_data = io.BytesIO(CASE_STUDY_CSV_PATH.read_bytes())
            sales, quality = prepare_simple_sales(case_data)
            source_label = "CSV do estudo de caso · VENDAS_PIZZARIA_BAIRRO (estabelecimento anonimizado)"
        elif source == MODE_CUSTOM_CSV:
            sales, quality, custom_import_result, source_label = render_external_csv_wizard(single_csv)
        elif source == MODE_FOUR_CSVS:
            if len(uploaded) != len(REQUIRED_UPLOADS):
                st.info("Envie os quatro CSVs para montar o painel. A base normalizada do projeto continua disponível.")
                st.stop()
            sales, quality = load_uploaded_csvs(
                uploaded,
                apply_project_recipe_rules=apply_project_recipe_rules,
            )
            source_label = "CSVs externos carregados pelo usuário · normalizados em memória"
        else:
            try:
                if not database_url:
                    raise RuntimeError("PIZZA_DATABASE_URL não está configurada.")
                sales, quality = load_sql_server(database_url)
                sql_connected = True
                source_label = "base pública original · SQL Server PizzaSales normalizado"
            except Exception as sql_error:
                try:
                    sales, quality = load_project_normalized_csvs()
                except Exception as fallback_error:
                    raise RuntimeError(
                        "SQL Server/ODBC não conectou e os CSVs normalizados locais não puderam ser carregados. "
                        f"SQL Server: {sql_error}. Base local: {fallback_error}"
                    ) from fallback_error
                source_label = "base pública original · CSVs normalizados locais (alternativa ao SQL Server)"
                error_text = str(sql_error)
                if "libodbc.so" in error_text.lower() or "unixodbc" in error_text.lower():
                    connection_cause = (
                        "Este processo local não encontrou a biblioteca unixODBC (libodbc.so.2) "
                        "necessária ao pyodbc."
                    )
                else:
                    connection_cause = f"Detalhe da conexão: {error_text}"
                sql_fallback_message = (
                    f"{connection_cause} O painel continuará com os dados normalizados locais. "
                    "Para usar SQL Server sem instalar ODBC no WSL, execute make all e use o painel Docker."
                )
    except Exception as error:
        st.error(f"Não foi possível carregar os dados: {error}")
        st.stop()

    if sales.empty:
        st.error("Não há linhas de venda válidas após os relacionamentos entre tabelas.")
        st.stop()

    min_date = sales["date"].min().date()
    max_date = sales["date"].max().date()
    if source in (MODE_PUBLIC, MODE_SQL_SERVER):
        chart_source_label = "Base pública · Pizza Place Sales"
    elif source == MODE_CASE_STUDY:
        chart_source_label = "Estudo de caso · VENDAS_PIZZARIA_BAIRRO"
    elif source == MODE_CUSTOM_CSV:
        chart_source_label = f"CSV · {getattr(single_csv, 'name', 'arquivo carregado')}"
    else:
        chart_source_label = "CSV externo da pizzaria"
    with st.sidebar:
        selected_dates = st.date_input(
            "Período analisado",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
            format="DD/MM/YYYY",
        )
        categories_available = sales["category"].notna().any()
        sizes_available = sales["size"].notna().any()
        selected_categories = None
        selected_sizes = None
        if categories_available:
            categories = sorted(sales["category"].dropna().astype(str).unique().tolist())
            selected_categories = st.multiselect("Categorias", categories, default=categories)
        if sizes_available:
            sizes = sorted(sales["size"].dropna().astype(str).unique().tolist())
            selected_sizes = st.multiselect("Tamanhos", sizes, default=sizes)

    if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
        start_date, end_date = selected_dates
    else:
        start_date = end_date = selected_dates
    start_timestamp = pd.Timestamp(start_date)
    end_timestamp = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)

    filter_mask = sales["date"].between(start_timestamp, end_timestamp)
    if selected_categories is not None:
        filter_mask &= sales["category"].isna() | sales["category"].astype(str).isin(selected_categories)
    if selected_sizes is not None:
        filter_mask &= sales["size"].isna() | sales["size"].astype(str).isin(selected_sizes)
    filtered = sales.loc[filter_mask].copy()
    commercial_mask = filtered["quantity"].gt(0)
    if filtered["order_id"].notna().any():
        if source != MODE_CUSTOM_CSV:
            commercial_mask &= filtered["order_id"].notna()
    commercial_filtered = filtered.loc[commercial_mask].copy()
    is_external_source = source in (MODE_CASE_STUDY, MODE_CUSTOM_CSV, MODE_FOUR_CSVS)
    closed_weekdays = tuple(DAY_NAMES.index(day) for day in closed_weekday_labels)
    if source == MODE_CUSTOM_CSV and custom_import_result is not None:
        closed_weekdays = custom_import_result.closed_weekdays
    if is_external_source:
        daily_series = build_daily_sales_series(
            filtered,
            start_date,
            end_date,
            closed_weekdays=closed_weekdays,
        )
        if source == MODE_CUSTOM_CSV and custom_import_result is not None:
            closed_sales_dates = set(custom_import_result.summary.get("closed_dates_with_sales", []))
            for unknown_day in custom_import_result.unknown_dates:
                if unknown_day not in pd.DatetimeIndex(daily_series["date"]):
                    continue
                if unknown_day in closed_sales_dates:
                    observed = filtered.loc[filtered["date"].eq(unknown_day), "quantity"].sum()
                    daily_series.loc[daily_series["date"].eq(unknown_day), "quantity"] = float(observed)
                else:
                    daily_series.loc[daily_series["date"].eq(unknown_day), "quantity"] = np.nan
    else:
        complete_dates = pd.date_range(
            pd.Timestamp(start_date).normalize(),
            pd.Timestamp(end_date).normalize(),
            freq="D",
        )
        daily_series = (
            filtered.groupby("date", as_index=False)["quantity"]
            .sum()
            .set_index("date")
            .reindex(complete_dates, fill_value=0)
            .rename_axis("date")
            .reset_index()
        )
    has_revenue = bool(
        not commercial_filtered.empty
        and commercial_filtered["revenue"].notna().all()
        and commercial_filtered["revenue"].notna().any()
    )
    order_id_series = commercial_filtered["order_id"].astype("string").str.strip().replace("", pd.NA)
    has_order_ids = bool(order_id_series.notna().any())
    complete_order_ids = bool(not commercial_filtered.empty and order_id_series.notna().all())
    if source == MODE_CUSTOM_CSV and "order_key" in commercial_filtered:
        order_count = int(commercial_filtered["order_key"].nunique(dropna=True)) if has_order_ids else None
    else:
        order_count = int(order_id_series.nunique(dropna=True)) if has_order_ids else None
    has_product = bool(commercial_filtered["product"].notna().any())
    has_category = bool(commercial_filtered["category"].notna().any())
    has_size = bool(commercial_filtered["size"].notna().any())
    has_hour = bool(commercial_filtered["hour"].notna().any())
    has_ingredients = bool(commercial_filtered["ingredients"].notna().any())

    valid_record_count = quality.get("linhas comerciais válidas", len(sales))
    st.caption(
        f"Fonte: {source_label} · Período: {min_date:%d/%m/%Y} a {max_date:%d/%m/%Y} · "
        f"Registros comerciais válidos: {valid_record_count}. Receita é bruta, não lucro."
    )
    if sql_fallback_message:
        st.warning(sql_fallback_message)
    if source == MODE_PUBLIC:
        st.success(
            "Análise conectada às tabelas normalizadas do ETL: pedidos → itens → pizzas → tipos → categorias; "
            "ingredientes entram pela associação pizza_type_ingredients."
        )
    elif source == MODE_SQL_SERVER and sql_connected:
        st.success("Análise executada por consultas somente de leitura nas tabelas normalizadas do SQL Server.")
    elif source == MODE_SQL_SERVER:
        st.info("Os indicadores abaixo estão usando os CSVs normalizados locais.")
    else:
        st.info(
            "Os dados enviados foram validados e preparados em memória. "
            "Campos ausentes não são inventados; as análises dependentes deles ficam indisponíveis."
        )
    if source == MODE_CUSTOM_CSV and custom_import_result is not None:
        if not complete_order_ids:
            st.warning(
                "Há linhas comerciais sem pedido_id. Elas permanecem nas vendas por produto e volume, "
                "mas não entram na contagem de pedidos; ticket médio e unidades por pedido ficam indisponíveis."
            )
        if not has_revenue:
            st.info("Faturamento e ticket médio exigem preço unitário positivo e preenchido em todas as linhas comerciais válidas.")
        if custom_import_result.unknown_dates:
            st.warning(
                f"A série temporal contém {len(custom_import_result.unknown_dates)} dia(s) sem informação confirmada. "
                "Esses pontos são mostrados como lacunas e não serão tratados como zero."
            )
    if filtered.empty:
        st.warning("Nenhuma venda corresponde aos filtros. Ajuste o período, as categorias ou os tamanhos.")
        st.stop()

    total_quantity = float(commercial_filtered["quantity"].sum())
    total_revenue = float(commercial_filtered["revenue"].sum()) if has_revenue else 0.0
    average_ticket = total_revenue / order_count if has_revenue and order_count and complete_order_ids else None
    average_pizzas = total_quantity / order_count if order_count and complete_order_ids else None

    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    kpi1.metric(
        "Receita bruta",
        format_compact_money(total_revenue, currency_symbol) if has_revenue else "—",
        help=(
            f"Valor completo: {format_money(total_revenue, currency_symbol)}"
            if has_revenue
            else "Informe preço unitário em todas as linhas para calcular receita."
        ),
    )
    kpi2.metric("Pizzas vendidas", format_number(total_quantity))
    kpi3.metric("Pedidos", format_number(order_count) if order_count is not None else "—")
    kpi4.metric("Valor médio por pedido", format_money(average_ticket, currency_symbol) if average_ticket is not None else "—")
    kpi5.metric("Pizzas por pedido", format_number(average_pizzas, 2) if average_pizzas is not None else "—")

    overview_tab, menu_tab, peak_tab, ingredient_tab, forecast_tab, model_tab, sql_tab, data_sources_tab = st.tabs(
        [
            "Visão geral",
            "Cardápio",
            "Picos de demanda",
            "Ingredientes",
            "Previsão",
            "ETL e modelo",
            "SQL · Base pública",
            "Sobre os dados",
        ]
    )

    with model_tab:
        st.caption(f"Fonte desta seção: {source_label}.")
        if source in (MODE_CASE_STUDY, MODE_CUSTOM_CSV):
            st.subheader("CSV de vendas preparado em memória")
            st.info(
                "O arquivo enviado não é gravado no banco nem convertido em sete tabelas permanentes. "
                "O painel usa apenas os campos disponíveis e não inventa categorias, pedidos, preços ou receitas."
            )
        else:
            st.subheader("Camada normalizada usada nas análises")
            st.write(
                "Os gráficos deste painel partem das tabelas relacionais abaixo. "
                "O cardápio usa as chaves de categoria; a análise de ingredientes usa a dimensão e a tabela associativa."
            )
        if source in (MODE_CASE_STUDY, MODE_CUSTOM_CSV):
            table_rows = [
                {"Fonte carregada": source_label, "Registros válidos": quality.get("linhas comerciais válidas", len(sales))}
            ]
        else:
            table_order = [
                "orders",
                "order_details",
                "pizzas",
                "pizza_types",
                "categories",
                "ingredients",
                "pizza_type_ingredients",
            ]
            table_rows = [
                {
                    "Tabela normalizada": table_name,
                    "Registros carregados": quality.get(f"tabela {table_name} (registros)", 0),
                }
                for table_name in table_order
            ]
        st.dataframe(pd.DataFrame(table_rows), hide_index=True, width="stretch")
        if source in (MODE_CASE_STUDY, MODE_CUSTOM_CSV):
            st.caption("O CSV é processado somente em memória; os dados de origem não são alterados.")
        else:
            st.markdown(
                "**Relacionamentos aplicados:** `orders 1:N order_details`; `pizzas 1:N order_details`; "
                "`pizza_types 1:N pizzas`; `categories 1:N pizza_types`; e "
                "`pizza_types N:M ingredients` por `pizza_type_ingredients`."
            )
            st.caption(
                "A receita bruta é calculada após relacionar quantity e price. A previsão usa a série diária "
                "resultante desses relacionamentos; não usa os ingredientes como se fossem quantidades consumidas."
            )
        st.markdown("**Auditoria desta carga**")
        st.json(quality)

    with sql_tab:
        st.subheader("Consultas SQL do projeto")
        st.caption(
            "Fonte desta seção: base pública original Pizza Place Sales. Selecione uma consulta do arquivo 03_analysis_queries.sql. A execução usa o SQL Server "
            "quando ele está conectado; sem essa conexão, usa as sete tabelas normalizadas locais. "
            "Estas consultas são independentes do CSV externo selecionado para os indicadores do painel."
        )
        try:
            available_queries = load_analysis_queries()
            query_labels = [
                f"{query['number']} · {query['title']}" for query in available_queries
            ]
            selected_label = st.selectbox("Consulta", query_labels, key="analysis_sql_query")
            selected_query = available_queries[query_labels.index(selected_label)]
            st.code(selected_query["sql"], language="sql")

            query_database_url = (
                database_url
                if source == MODE_SQL_SERVER
                else os.environ.get("PIZZA_DATABASE_URL", "").strip()
            )
            result, execution_source = execute_analysis_query(
                selected_query["sql"],
                database_url=query_database_url,
                require_sql_server=False,
            )
            st.caption(f"Executada em: {execution_source}")
            if source == MODE_SQL_SERVER and execution_source.startswith("SQLite"):
                st.warning("SQL Server/ODBC indisponível nesta execução; a consulta foi executada na base normalizada local.")
            if result.empty:
                st.info("A consulta foi executada sem erros e não retornou linhas.")
            st.dataframe(result, hide_index=True, width="stretch")
        except Exception as error:
            st.error(f"Não foi possível carregar ou executar a consulta: {error}")

    with overview_tab:
        st.caption(f"Fonte desta seção: {source_label}.")
        st.subheader("Evolução das vendas")
        if is_external_source:
            daily_summary = daily_series.copy()
            if has_revenue:
                revenue_by_date = (
                    commercial_filtered.groupby("date")["revenue"]
                    .sum()
                    .reindex(pd.DatetimeIndex(daily_summary["date"]), fill_value=0)
                )
                daily_summary["revenue"] = revenue_by_date.to_numpy()
            if source == MODE_CUSTOM_CSV and custom_import_result is not None:
                unresolved = set(custom_import_result.unknown_dates) - set(
                    custom_import_result.summary.get("closed_dates_with_sales", [])
                )
                unknown_mask = pd.DatetimeIndex(daily_summary["date"]).isin(unresolved)
                daily_summary.loc[unknown_mask, "quantity"] = np.nan
                if has_revenue:
                    daily_summary.loc[unknown_mask, "revenue"] = np.nan
        else:
            daily_aggregations = {"quantity": ("quantity", "sum")}
            if has_revenue:
                daily_aggregations["revenue"] = ("revenue", "sum")
            daily_summary = (
                filtered.groupby("date", as_index=False)
                .agg(**daily_aggregations)
                .sort_values("date")
            )
        if has_revenue:
            left, right = st.columns(2)
            with left:
                revenue_fig = px.line(
                    daily_summary,
                    x="date",
                    y="revenue",
                    markers=True,
                    title=f"Receita bruta por dia · {chart_source_label}",
                    labels={"date": "Data", "revenue": "Receita (moeda da base)"},
                )
                revenue_fig.update_traces(line_color="#176B87")
                revenue_fig.update_layout(hovermode="x unified")
                st.plotly_chart(revenue_fig, width="stretch")
            with right:
                quantity_fig = px.line(
                    daily_summary,
                    x="date",
                    y="quantity",
                    markers=True,
                    title=f"Pizzas vendidas por dia · {chart_source_label}",
                    labels={"date": "Data", "quantity": "Pizzas"},
                )
                quantity_fig.update_traces(line_color="#E07A2D")
                quantity_fig.update_layout(hovermode="x unified")
                st.plotly_chart(quantity_fig, width="stretch")
        else:
            st.info("O CSV não tem preço unitário completo; o gráfico de receita bruta não está disponível.")
            revenue_fig = px.line(
                daily_summary,
                x="date",
                y="quantity",
                markers=True,
                title=f"Pizzas vendidas por dia · {chart_source_label}",
                labels={"date": "Data", "quantity": "Pizzas"},
            )
            revenue_fig.update_traces(line_color="#E07A2D")
            revenue_fig.update_layout(hovermode="x unified")
            st.plotly_chart(revenue_fig, width="stretch")

        st.subheader("Resumo por dia da semana")
        if is_external_source:
            weekday_totals = (
                daily_series.assign(weekday_num=daily_series["date"].dt.day_of_week)
                .groupby("weekday_num")["quantity"]
                .sum()
                .reindex(range(7), fill_value=0)
            )
            weekday_summary = pd.DataFrame(
                {
                    "weekday": pd.Categorical(DAY_NAMES, categories=DAY_NAMES, ordered=True),
                    "pizzas": weekday_totals.to_numpy(),
                }
            )
        else:
            weekday_summary = (
                filtered.groupby("weekday", observed=False, as_index=False)
                .agg(pizzas=("quantity", "sum"))
            )
        weekday_fig = px.bar(
            weekday_summary,
            x="weekday",
            y="pizzas",
            title=f"Volume de pizzas por dia da semana · {chart_source_label}",
            labels={"weekday": "Dia", "pizzas": "Pizzas vendidas"},
            category_orders={"weekday": DAY_NAMES},
            color="pizzas",
            color_continuous_scale="Oranges",
        )
        st.plotly_chart(weekday_fig, width="stretch")

    with menu_tab:
        st.caption(f"Fonte desta seção: {source_label}.")
        st.subheader("Desempenho do cardápio")
        menu_available = has_product or has_category or has_size
        if not menu_available:
            st.info("Informe produto, categoria ou tamanho no CSV para habilitar análises do cardápio.")
        else:
            if has_category:
                category_aggregations = {"pizzas": ("quantity", "sum")}
                if has_revenue:
                    category_aggregations["receita"] = ("revenue", "sum")
                category_summary = (
                    commercial_filtered.dropna(subset=["category"])
                    .groupby("category", as_index=False)
                    .agg(**category_aggregations)
                )
                if not category_summary.empty:
                    metric_column = "receita" if has_revenue else "pizzas"
                    category_fig = px.bar(
                        category_summary,
                        x="category",
                        y=metric_column,
                        color="category",
                        title=(
                            f"Receita bruta por categoria · {chart_source_label}"
                            if has_revenue
                            else f"Pizzas vendidas por categoria · {chart_source_label}"
                        ),
                        labels={
                            "category": "Categoria",
                            metric_column: "Receita (moeda da base)" if has_revenue else "Pizzas vendidas",
                        },
                    )
                    st.plotly_chart(category_fig, width="stretch")
                else:
                    st.info("Não há categorias preenchidas no período filtrado.")

            if has_size:
                size_summary = (
                    commercial_filtered.dropna(subset=["size"])
                    .groupby("size", as_index=False)
                    .agg(pizzas=("quantity", "sum"))
                )
                if not size_summary.empty:
                    size_fig = px.pie(
                        size_summary,
                        names="size",
                        values="pizzas",
                        title=f"Participação dos tamanhos nas unidades vendidas · {chart_source_label}",
                        labels={"size": "Tamanho", "pizzas": "Pizzas vendidas"},
                        hole=0.45,
                    )
                    st.plotly_chart(size_fig, width="stretch")
                else:
                    st.info("Não há tamanhos preenchidos no período filtrado.")

            if has_product:
                group_columns = ["product"]
                if categories_available:
                    group_columns.append("category")
                product_aggregations = {"pizzas": ("quantity", "sum")}
                if has_revenue:
                    product_aggregations["receita"] = ("revenue", "sum")
                top_products = commercial_filtered.groupby(group_columns, as_index=False, dropna=False).agg(
                    **product_aggregations
                )
                top_products = top_products.sort_values(
                    "receita" if has_revenue else "pizzas",
                    ascending=False,
                ).head(15)
                if has_revenue:
                    top_products["receita"] = top_products["receita"].map(
                        lambda amount: format_money(float(amount), currency_symbol)
                    )
                st.markdown("**Pizzas mais vendidas**")
                st.dataframe(
                    top_products.rename(
                        columns={
                            "product": "Produto",
                            "category": "Categoria",
                            "pizzas": "Pizzas vendidas",
                            "receita": "Receita bruta",
                        }
                    ),
                    hide_index=True,
                    width="stretch",
                )

    with peak_tab:
        st.caption(f"Fonte desta seção: {source_label}.")
        st.subheader("Em quais horários se concentra o movimento?")
        if not has_hour:
            st.info("O CSV não informa horário. Inclua uma coluna hora/horario para analisar picos intradiários.")
        else:
            st.caption(
                "O mapa mostra o volume de pizzas por dia e hora informados. "
                "Ele apoia a escala, mas não mede tempo de preparo nem capacidade da cozinha."
            )
            timed_sales = commercial_filtered.dropna(subset=["hour"]).copy()
            if timed_sales.empty:
                st.info("Não há horários válidos no período filtrado.")
            else:
                heatmap = timed_sales.pivot_table(
                    index="weekday",
                    columns="hour",
                    values="quantity",
                    aggfunc="sum",
                    fill_value=0,
                    observed=False,
                ).reindex(DAY_NAMES)
                heatmap = heatmap.reindex(columns=range(24), fill_value=0)
                heatmap_fig = px.imshow(
                    heatmap,
                    aspect="auto",
                    color_continuous_scale="Oranges",
                    labels={"x": "Hora do pedido", "y": "Dia da semana", "color": "Pizzas"},
                    title=f"Mapa de calor: pizzas vendidas por dia e hora · {chart_source_label}",
                )
                heatmap_fig.update_xaxes(tickmode="array", tickvals=list(range(24)), ticktext=[f"{hour:02d}h" for hour in range(24)])
                st.plotly_chart(heatmap_fig, width="stretch")

                hourly_summary = timed_sales.groupby("hour", as_index=False).agg(pizzas=("quantity", "sum"))
                busiest = hourly_summary.sort_values("pizzas", ascending=False).head(5)
                st.markdown("**Cinco horas com maior volume**")
                st.dataframe(
                    busiest.rename(columns={"hour": "Horário", "pizzas": "Pizzas vendidas"}),
                    hide_index=True,
                    width="stretch",
                )

    with ingredient_tab:
        st.caption(f"Fonte desta seção: {source_label}.")
        st.subheader("Ingredientes associados às vendas")
        if not has_ingredients:
            st.info("A origem não trouxe a lista de ingredientes. Ela é necessária para esta análise.")
        else:
            if source in (MODE_CASE_STUDY, MODE_CUSTOM_CSV):
                st.caption("A lista de ingredientes veio do CSV enviado; o painel não acrescenta ingredientes por suposição.")
            else:
                st.caption(
                    "A composição vem da dimensão ingredients e da tabela associativa "
                    "pizza_type_ingredients. Em CSV, o painel reproduz as regras de limpeza do ETL do projeto."
                )
            ingredient_lines = commercial_filtered[["ingredients", "quantity"]].dropna(subset=["ingredients"]).copy()
            ingredient_lines = ingredient_lines.reset_index(drop=True)
            ingredient_lines["sale_line_id"] = range(len(ingredient_lines))
            ingredient_lines["ingredient"] = ingredient_lines["ingredients"].astype(str).str.split(r"[,;]")
            ingredient_lines = ingredient_lines.explode("ingredient")
            ingredient_lines["ingredient"] = ingredient_lines["ingredient"].astype(str).str.strip()
            ingredient_lines = ingredient_lines[ingredient_lines["ingredient"].ne("")].drop_duplicates(
                subset=["sale_line_id", "ingredient"], keep="first"
            )
            # A contagem é uma associação com receitas vendidas, não consumo físico do ingrediente.
            ingredient_summary = (
                ingredient_lines.groupby("ingredient", as_index=False)["quantity"]
                .sum()
                .rename(columns={"quantity": "pizzas em receitas com o ingrediente"})
                .sort_values("pizzas em receitas com o ingrediente", ascending=False)
                .head(20)
            )
            st.caption(
                "Este indicador conta pizzas vendidas cujas receitas listam cada ingrediente. "
                "A base não informa gramas por receita, estoque ou custo; portanto, não representa consumo real nem custo."
            )
            ingredient_fig = px.bar(
                ingredient_summary.sort_values("pizzas em receitas com o ingrediente"),
                x="pizzas em receitas com o ingrediente",
                y="ingredient",
                orientation="h",
                title=f"Pizzas vendidas em receitas que incluem o ingrediente · {chart_source_label}",
                labels={"ingredient": "Ingrediente", "pizzas em receitas com o ingrediente": "Pizzas"},
                color="pizzas em receitas com o ingrediente",
                color_continuous_scale="Oranges",
            )
            st.plotly_chart(ingredient_fig, width="stretch")
            st.dataframe(
                ingredient_summary.rename(columns={"ingredient": "Ingrediente"}),
                hide_index=True,
                width="stretch",
            )

    with forecast_tab:
        st.caption(f"Fonte desta seção: {source_label}.")
        st.subheader("Previsão de demanda para sete dias")
        st.caption(
            "A regressão usa a série diária completa somente quando o calendário e os dias sem registro "
            "permitem interpretar a série. Dias confirmados como fechados recebem previsão zero; nos demais, "
            "é usado o modelo existente."
        )
        forecast_daily = daily_series.copy()
        if source == MODE_CUSTOM_CSV and custom_import_result is not None and not custom_import_result.forecast_ready:
            st.info(
                "Previsão suspensa: confirme o calendário, confira as linhas com data/quantidade inválidas e "
                "resolva os dias desconhecidos. A série diária não substituirá esses valores por zero."
            )
        elif len(forecast_daily) < 56:
            st.info(
                f"Selecione um período com pelo menos 56 dias completos. "
                f"O período atual tem {len(forecast_daily)} dias."
            )
        else:
            try:
                model_module = load_forecast_module()
                test_size = max(14, int(np.ceil(len(forecast_daily) * 0.20)))
                if closed_weekdays:
                    metrics, backtest = evaluate_pizzeria_walk_forward(
                        model_module,
                        forecast_daily,
                        test_size,
                        closed_weekdays=closed_weekdays,
                    )
                else:
                    metrics, backtest = model_module.evaluate_walk_forward(forecast_daily, test_size)
                origin_date = pd.Timestamp(forecast_daily["date"].iloc[0])
                history = forecast_daily.set_index("date")["quantity"].astype(float)
                x_all, y_all = model_module.make_training_data(history, origin_date)
                model = model_module.LinearRegression().fit(x_all, y_all)
                forecast_dates = pd.date_range(
                    forecast_daily["date"].iloc[-1] + pd.Timedelta(days=1), periods=7, freq="D"
                )
                if closed_weekdays:
                    predictions, forecast_features = predict_pizzeria_recursively(
                        model_module,
                        model,
                        history,
                        forecast_dates,
                        origin_date,
                        closed_weekdays=closed_weekdays,
                    )
                else:
                    predictions, forecast_features = model_module.predict_recursively(
                        model, history, forecast_dates, origin_date
                    )
                mae = metrics["mae"]
                forecast_table = pd.DataFrame(
                    {
                        "Data": forecast_dates.strftime("%d/%m/%Y"),
                        "Dia": [DAY_NAMES[date.day_of_week] for date in forecast_dates],
                        "Venda na semana anterior": np.rint(forecast_features["lag_7d"].to_numpy()).astype(int),
                        "Média móvel 7 dias": np.round(forecast_features["rolling_7d"].to_numpy(), 1),
                        "Previsão de pizzas": np.rint(predictions).astype(int),
                        "Faixa inferior indicativa": np.maximum(0, np.floor(predictions - mae)).astype(int),
                        "Faixa superior indicativa": np.ceil(predictions + mae).astype(int),
                    }
                )

                metric_a, metric_b, metric_c = st.columns(3)
                metric_a.metric("MAE do modelo", f"{metrics['mae']:.1f} pizzas/dia")
                metric_b.metric("MAE de referência (lag_7d)", f"{metrics['baseline_mae']:.1f} pizzas/dia")
                metric_c.metric("R² na avaliação", f"{metrics['r2']:.3f}")
                if metrics["mae"] > metrics["baseline_mae"]:
                    st.warning("Neste histórico, a regressão teve erro maior que repetir as vendas da semana anterior.")
                st.dataframe(forecast_table, hide_index=True, width="stretch")

                fig = go.Figure()
                recent_start = forecast_daily["date"].max() - pd.Timedelta(days=55)
                recent = forecast_daily[forecast_daily["date"] >= recent_start]
                recent_backtest = backtest[backtest["date"] >= recent_start]
                fig.add_trace(go.Scatter(x=recent["date"], y=recent["quantity"], mode="lines", name="Vendas reais", line={"color": "#176B87"}))
                fig.add_trace(go.Scatter(x=recent_backtest["date"], y=recent_backtest["predicted"], mode="lines", name="Avaliação retrospectiva", line={"color": "#E07A2D", "dash": "dash"}))
                fig.add_trace(go.Scatter(x=forecast_dates, y=predictions + mae, mode="lines", line={"width": 0}, showlegend=False, hoverinfo="skip"))
                fig.add_trace(go.Scatter(x=forecast_dates, y=np.maximum(0, predictions - mae), mode="lines", line={"width": 0}, fill="tonexty", fillcolor="rgba(168,50,90,0.16)", name="Faixa indicativa ± MAE", hoverinfo="skip"))
                fig.add_trace(go.Scatter(x=forecast_dates, y=predictions, mode="lines+markers", name="Previsão 7 dias", line={"color": "#A8325A", "width": 3}))
                fig.update_layout(
                    title=f"Vendas reais, avaliação do modelo e previsão · {chart_source_label}",
                    xaxis_title="Data",
                    yaxis_title="Pizzas",
                    hovermode="x unified",
                    legend_title="Série",
                )
                fig.update_xaxes(tickformat="%d/%m/%Y")
                st.plotly_chart(fig, width="stretch")
                st.caption("A faixa previsão ± MAE é indicativa, não um intervalo de confiança. A previsão inicia no dia seguinte ao fim do período selecionado.")
            except Exception as error:
                st.error(f"Não foi possível calcular a previsão: {error}")

    with data_sources_tab:
        st.subheader("De onde vêm os dados")
        st.markdown(
            "O painel tem duas etapas de uso: a base pública serviu ao desenvolvimento técnico original; "
            "a ingestão de CSV foi acrescentada depois para que outras pizzarias possam analisar seus próprios dados. "
            "As fontes são carregadas e analisadas separadamente."
        )
        public_column, external_column = st.columns(2)
        with public_column:
            with st.container(border=True):
                st.markdown("**Base pública original — Pizza Place Sales**")
                st.write(
                    "Conjunto divulgado para o Maven Pizza Challenge e creditado na página do conjunto a "
                    "Vincent Arel-Bundock / Rdatasets. O desafio descreve vendas de um estabelecimento fictício; "
                    "portanto, esses valores não pertencem à Pizzaria de Bairro."
                )
                st.markdown(
                    "Origem: [Maven Pizza Challenge](https://mavenanalytics.io/challenges/maven-pizza-challenge)  \n"
                    "Crédito e licença informada: [Pizza Place Sales — Maven Data Playground](https://status.mavenanalytics.io/data-playground/pizza-place-sales)  \n"
                    "Período da base local: 01/01/2015 a 31/12/2015."
                )
                st.write(
                    f"Registros de itens na camada normalizada: "
                    f"{quality.get('tabela order_details (registros)', 'não disponível')}; "
                    f"pedidos: {quality.get('tabela orders (registros)', 'não disponível')}. "
                    "A base está organizada em sete tabelas relacionais: orders, order_details, pizzas, "
                    "pizza_types, categories, ingredients e pizza_type_ingredients."
                )
                st.caption(
                    "Os valores monetários e as categorias da base pública pertencem ao contexto original do conjunto; "
                    "a seleção de moeda altera somente o símbolo, sem conversão."
                )
        with external_column:
            with st.container(border=True):
                st.markdown("**CSV externo — análise personalizada**")
                st.write(
                    "O modo CSV processa dados de um estabelecimento escolhido pelo usuário. "
                    "O estudo de caso utilizado nesta apresentação é o arquivo "
                    "`VENDAS_PIZZARIA_BAIRRO.csv`; o nome comercial foi omitido para preservar a identificação. "
                    "O arquivo representa dados da pizzaria de bairro, não a base pública."
                )
                st.write(
                    f"Fonte selecionada agora: {source_label}. Período visível: "
                    f"{min_date:%d/%m/%Y} a {max_date:%d/%m/%Y}; "
                    f"{quality.get('linhas comerciais válidas', len(sales))} registros comerciais válidos."
                )
                st.markdown(
                    "Para uma nova análise, carregue um CSV próprio. O painel reconhece `data`/`date` e "
                    "`quantidade`/`quantity` como campos obrigatórios. `pedido_id`, `hora`, `produto`, `tamanho`, "
                    "`preco_unitario`, `categoria` e `ingredientes` são opcionais; cada um habilita somente "
                    "as análises correspondentes."
                )
                st.caption(
                    "Datas podem ser fornecidas em AAAA-MM-DD; preço unitário deve ser informado por unidade. "
                    "A moeda é declarada pelo usuário e não é convertida. Sem custos registrados, receita bruta não é lucro."
                )
        st.markdown("**Modelo de arquivo**")
        st.download_button(
            "Baixar modelo de CSV para vendas",
            data=CSV_TEMPLATE_PATH.read_bytes(),
            file_name="modelo_csv_vendas_pizzaria.csv",
            mime="text/csv",
            key="download_generic_sales_template",
        )
        st.caption(
            "No modelo, cada linha representa um item vendido; quantidade é o número de unidades da linha. "
            "O período, cardápio, tamanhos, categorias e funcionamento devem refletir cada estabelecimento."
        )

    with st.expander("Qualidade dos dados e interpretação"):
        if source in (MODE_CASE_STUDY, MODE_CUSTOM_CSV):
            st.write(
                "O CSV é tratado em memória. Data e quantidade são obrigatórias; cada análise adicional "
                "depende de seu respectivo campo estar preenchido. Valores ausentes não são estimados."
            )
            st.markdown(
                "Campos reconhecidos: data/date, quantidade/quantity, pedido_id/order_id, hora/time, "
                "produto/product, tamanho/size, preco_unitario/unit_price, categoria/category e ingredientes."
            )
        else:
            st.write(
                "A fonte padrão lê diretamente as sete tabelas normalizadas em data/normalized/. "
                "A opção SQL Server consulta essas mesmas entidades no banco; arquivos enviados "
                "passam pela validação e normalização em memória. Categorias e ingredientes são relacionados "
                "por suas dimensões e pela tabela associativa. Chaves sem correspondência são contabilizadas."
            )
        if source == MODE_FOUR_CSVS and not apply_project_recipe_rules:
            st.markdown(
                "**Tratamento aplicado aos CSVs enviados:** categorias separadas em dimensão própria; "
                "ingredientes divididos, espaços removidos e `Artichoke` padronizado para `Artichokes`. "
                "As regras de adição de mozzarella e molho foram desmarcadas para respeitar o cardápio informado."
            )
        elif source == MODE_FOUR_CSVS:
            st.markdown(
                "**Tratamento aplicado aos CSVs enviados:** categorias separadas em dimensão própria; "
                "ingredientes divididos, espaços removidos, `Artichoke` padronizado para `Artichokes`, "
                "Mozzarella Cheese adicionado e Tomato Sauce incluído quando não há outro molho."
            )
        elif source in (MODE_PUBLIC, MODE_SQL_SERVER):
            st.markdown(
                "**Regras do ETL gravadas na camada normalizada:** divisão da lista de ingredientes; "
                "remoção de espaços; padronização de `Artichoke` para `Artichokes`; "
                "adição de `Mozzarella Cheese` a todas as receitas; e adição de `Tomato Sauce` "
                "somente quando a receita original não contém outro molho. Esses registros são lidos "
                "das tabelas `ingredients` e `pizza_type_ingredients`, sem reconstruir receitas a partir "
                "do CSV desnormalizado."
            )
        st.json(quality)
        st.warning(
            "Receita bruta não é lucro. Para medir rentabilidade e consumo real de ingredientes, "
            "a pizzaria precisa registrar custos e quantidades de cada ingrediente por receita."
        )

    csv_export = commercial_filtered.drop(columns=["order_key"], errors="ignore")
    csv_bytes = csv_export.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Baixar vendas filtradas (CSV)",
        data=csv_bytes,
        file_name="vendas_filtradas_pizzaria.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
