"""Dashboard Streamlit para análise de vendas de pizzarias.

A fonte padrão são as sete tabelas normalizadas em data/normalized/. Também aceita
quatro CSVs de outra pizzaria ou consultas somente de leitura ao SQL Server.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import create_engine, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = PROJECT_ROOT / "src" / "02_regressao_linear_vendas_diarias.py"
NORMALIZED_DATA_DIR = PROJECT_ROOT / "data" / "normalized"
ANALYSIS_QUERIES_PATH = PROJECT_ROOT / "03_analysis_queries.sql"
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


st.set_page_config(
    page_title="Pizza Analytics | UNIVESP",
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
    merged["weekday_num"] = merged["order_datetime"].dt.dayofweek
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
    sales["weekday_num"] = sales["order_datetime"].dt.dayofweek
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
    sales["weekday_num"] = sales["order_datetime"].dt.dayofweek
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
    # Estas consultas fixas são reescritas como LEFT JOIN para compatibilidade com WSL antigo.
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
    # signature invalida o cache quando `make normalize` atualiza qualquer tabela.
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


def main() -> None:
    st.title("🍕 Pizza Analytics")
    st.caption("Projeto Integrador IV · UNIVESP | Automação de dados e apoio à gestão de pizzarias")

    with st.sidebar:
        st.header("Dados e filtros")
        source = st.radio(
            "Fonte dos dados",
            ["Base normalizada do projeto", "Enviar CSVs da pizzaria", "Banco SQL Server normalizado"],
        )
        uploaded: dict[str, object] = {}
        database_url = ""
        apply_project_recipe_rules = True
        if source == "Base normalizada do projeto":
            st.caption("Carrega as sete tabelas exportadas pelo ETL em data/normalized/.")
        if source == "Enviar CSVs da pizzaria":
            st.caption("Envie quatro tabelas do sistema de vendas. Os campos mínimos estão no manual do painel.")
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
        elif source == "Banco SQL Server normalizado":
            database_url = os.environ.get("PIZZA_DATABASE_URL", "").strip()
            st.caption("Conexão somente para leitura. Configure PIZZA_DATABASE_URL no ambiente antes de iniciar o app.")
            if database_url:
                st.success("PIZZA_DATABASE_URL encontrada no ambiente.")
            else:
                st.info("Sem URL configurada. Veja o manual do painel para conectar ao banco PizzaSales.")

        symbol_options = ["US$", "R$", "Sem símbolo"]
        currency_label = st.selectbox(
            "Símbolo da moeda exibida (sem conversão)",
            symbol_options,
            index=0 if source == "Base normalizada do projeto" else 1,
        )
        currency_symbol = "" if currency_label == "Sem símbolo" else currency_label

        st.divider()
        st.markdown("**Projeto Integrador IV**")
        st.caption("Polo CEU Anhanguera · Polo CEU Carrão")
        st.caption("Orientador: Vinícius Alexandre Ramos Simão")

    try:
        if source == "Base normalizada do projeto":
            sales, quality = load_project_normalized_csvs()
            source_label = "camada normalizada do ETL · data/normalized/"
        elif source == "Enviar CSVs da pizzaria":
            if len(uploaded) != len(REQUIRED_UPLOADS):
                st.info("Envie os quatro CSVs para montar o painel. A camada normalizada do projeto continua disponível no menu lateral.")
                st.stop()
            sales, quality = load_uploaded_csvs(
                uploaded,
                apply_project_recipe_rules=apply_project_recipe_rules,
            )
            source_label = "CSVs tratados e normalizados nesta sessão"
        else:
            if not database_url:
                st.stop()
            sales, quality = load_sql_server(database_url)
            source_label = "SQL Server · PizzaSales normalizado"
    except Exception as error:
        st.error(f"Não foi possível carregar os dados: {error}")
        st.stop()

    if sales.empty:
        st.error("Não há linhas de venda válidas após os relacionamentos entre tabelas.")
        st.stop()

    min_date = sales["date"].min().date()
    max_date = sales["date"].max().date()
    with st.sidebar:
        selected_dates = st.date_input(
            "Período analisado",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )
        categories = sorted(sales["category"].dropna().astype(str).unique().tolist())
        selected_categories = st.multiselect("Categorias", categories, default=categories)
        sizes = sorted(sales["size"].dropna().astype(str).unique().tolist())
        selected_sizes = st.multiselect("Tamanhos", sizes, default=sizes)

    if isinstance(selected_dates, tuple) and len(selected_dates) == 2:
        start_date, end_date = selected_dates
    else:
        start_date = end_date = selected_dates
    start_timestamp = pd.Timestamp(start_date)
    end_timestamp = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)

    filtered = sales.loc[
        sales["date"].between(start_timestamp, end_timestamp)
        & sales["category"].astype(str).isin(selected_categories)
        & sales["size"].astype(str).isin(selected_sizes)
    ].copy()

    st.caption(
        f"Fonte: {source_label} · Período disponível: {min_date:%d/%m/%Y} a {max_date:%d/%m/%Y} · "
        "Receita é bruta; a base não contém custos para calcular lucro."
    )
    if source == "Base normalizada do projeto":
        st.success(
            "Análise conectada às tabelas normalizadas do ETL: pedidos → itens → pizzas → tipos → categorias; "
            "ingredientes entram pela associação pizza_type_ingredients."
        )
    elif source == "Banco SQL Server normalizado":
        st.success("Análise executada por consultas somente de leitura nas tabelas normalizadas do SQL Server.")
    else:
        st.info("Os CSVs enviados foram validados e relacionados; categorias e receitas foram normalizadas em memória.")
    if filtered.empty:
        st.warning("Nenhuma venda corresponde aos filtros. Ajuste o período, as categorias ou os tamanhos.")
        st.stop()

    total_quantity = float(filtered["quantity"].sum())
    total_revenue = float(filtered["revenue"].sum())
    order_count = int(filtered["order_id"].nunique())
    average_ticket = total_revenue / order_count if order_count else 0.0
    average_pizzas = total_quantity / order_count if order_count else 0.0

    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    kpi1.metric(
        "Receita bruta",
        format_compact_money(total_revenue, currency_symbol),
        help=f"Valor completo: {format_money(total_revenue, currency_symbol)}",
    )
    kpi2.metric("Pizzas vendidas", format_number(total_quantity))
    kpi3.metric("Pedidos", format_number(order_count))
    kpi4.metric("Ticket médio", format_money(average_ticket, currency_symbol))
    kpi5.metric("Pizzas por pedido", format_number(average_pizzas, 2))

    overview_tab, menu_tab, peak_tab, ingredient_tab, forecast_tab, model_tab, sql_tab = st.tabs(
        [
            "Visão geral",
            "Cardápio",
            "Picos de demanda",
            "Ingredientes",
            "Previsão",
            "ETL e modelo",
            "Consultas SQL",
        ]
    )

    with model_tab:
        st.subheader("Camada normalizada usada nas análises")
        st.write(
            "Os gráficos deste painel partem das tabelas relacionais abaixo. "
            "O cardápio usa as chaves de categoria; a análise de ingredientes usa a dimensão e a tabela associativa."
        )
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
        st.dataframe(pd.DataFrame(table_rows), hide_index=True, use_container_width=True)
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
            "Selecione uma consulta do arquivo 03_analysis_queries.sql. A execução usa o SQL Server "
            "quando ele está conectado; sem essa conexão, usa as sete tabelas normalizadas locais. "
            "Os filtros laterais e os CSVs enviados não alteram estas consultas."
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
                if source == "Banco SQL Server normalizado"
                else os.environ.get("PIZZA_DATABASE_URL", "").strip()
            )
            result, execution_source = execute_analysis_query(
                selected_query["sql"],
                database_url=query_database_url,
                require_sql_server=(source == "Banco SQL Server normalizado"),
            )
            st.caption(f"Executada em: {execution_source}")
            if result.empty:
                st.info("A consulta foi executada sem erros e não retornou linhas.")
            st.dataframe(result, hide_index=True, use_container_width=True)
        except Exception as error:
            st.error(f"Não foi possível carregar ou executar a consulta: {error}")

    with overview_tab:
        st.subheader("Evolução das vendas")
        daily_summary = (
            filtered.groupby("date", as_index=False)
            .agg(quantity=("quantity", "sum"), revenue=("revenue", "sum"), orders=("order_id", "nunique"))
            .sort_values("date")
        )
        left, right = st.columns(2)
        with left:
            revenue_fig = px.line(
                daily_summary,
                x="date",
                y="revenue",
                markers=True,
                title="Receita bruta por dia",
                labels={"date": "Data", "revenue": "Receita (moeda da base)"},
            )
            revenue_fig.update_traces(line_color="#176B87")
            revenue_fig.update_layout(hovermode="x unified")
            st.plotly_chart(revenue_fig, use_container_width=True)
        with right:
            quantity_fig = px.line(
                daily_summary,
                x="date",
                y="quantity",
                markers=True,
                title="Pizzas vendidas por dia",
                labels={"date": "Data", "quantity": "Pizzas"},
            )
            quantity_fig.update_traces(line_color="#E07A2D")
            quantity_fig.update_layout(hovermode="x unified")
            st.plotly_chart(quantity_fig, use_container_width=True)

        st.subheader("Resumo por dia da semana")
        weekday_summary = (
            filtered.groupby("weekday", observed=False, as_index=False)
            .agg(pizzas=("quantity", "sum"), receita=("revenue", "sum"), pedidos=("order_id", "nunique"))
        )
        weekday_fig = px.bar(
            weekday_summary,
            x="weekday",
            y="pizzas",
            title="Volume de pizzas por dia da semana",
            labels={"weekday": "Dia", "pizzas": "Pizzas vendidas"},
            category_orders={"weekday": DAY_NAMES},
            color="pizzas",
            color_continuous_scale="Oranges",
        )
        st.plotly_chart(weekday_fig, use_container_width=True)

    with menu_tab:
        st.subheader("Desempenho do cardápio")
        category_summary = (
            filtered.groupby("category", as_index=False)
            .agg(pizzas=("quantity", "sum"), receita=("revenue", "sum"))
            .sort_values("receita", ascending=False)
        )
        top_products = (
            filtered.groupby(["product", "category", "size"], as_index=False)
            .agg(pizzas=("quantity", "sum"), receita=("revenue", "sum"))
            .sort_values("pizzas", ascending=False)
        )
        cat_col, size_col = st.columns(2)
        with cat_col:
            category_fig = px.bar(
                category_summary,
                x="category",
                y="receita",
                color="category",
                title="Receita bruta por categoria",
                labels={"category": "Categoria", "receita": "Receita (moeda da base)"},
            )
            st.plotly_chart(category_fig, use_container_width=True)
        with size_col:
            size_summary = filtered.groupby("size", as_index=False).agg(pizzas=("quantity", "sum"))
            size_fig = px.pie(
                size_summary,
                names="size",
                values="pizzas",
                title="Participação dos tamanhos nas unidades vendidas",
                hole=0.45,
            )
            st.plotly_chart(size_fig, use_container_width=True)

        st.markdown("**Pizzas mais vendidas**")
        display_products = top_products.head(15).copy()
        display_products["receita"] = display_products["receita"].map(
            lambda amount: format_money(float(amount), currency_symbol)
        )
        st.dataframe(display_products, hide_index=True, use_container_width=True)

    with peak_tab:
        st.subheader("Quando a pizzaria recebe mais pedidos?")
        st.caption("O mapa combina dia da semana e hora registrada no pedido. Ele apoia escala e preparo; não mede tempo de cozinha.")
        heatmap = filtered.pivot_table(
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
            title="Mapa de calor: pizzas vendidas por dia e hora",
        )
        heatmap_fig.update_xaxes(tickmode="array", tickvals=list(range(24)), ticktext=[f"{hour:02d}h" for hour in range(24)])
        st.plotly_chart(heatmap_fig, use_container_width=True)

        hourly_summary = filtered.groupby("hour", as_index=False).agg(pizzas=("quantity", "sum"), pedidos=("order_id", "nunique"))
        busiest = hourly_summary.sort_values("pizzas", ascending=False).head(5)
        st.markdown("**Cinco horas com maior volume**")
        st.dataframe(busiest, hide_index=True, use_container_width=True)

    with ingredient_tab:
        st.subheader("Ingredientes associados às vendas")
        if "ingredients" not in filtered.columns or filtered["ingredients"].isna().all():
            st.info("A origem não trouxe a lista de ingredientes. Ela é necessária para esta análise.")
        else:
            st.caption(
                "A composição vem da dimensão ingredients e da tabela associativa "
                "pizza_type_ingredients. Em CSV, o painel reproduz as regras de limpeza do ETL do projeto."
            )
            ingredient_lines = filtered[["ingredients", "quantity"]].dropna(subset=["ingredients"]).copy()
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
                title="Pizzas vendidas em receitas que incluem o ingrediente",
                labels={"ingredient": "Ingrediente", "pizzas em receitas com o ingrediente": "Pizzas"},
                color="pizzas em receitas com o ingrediente",
                color_continuous_scale="Oranges",
            )
            st.plotly_chart(ingredient_fig, use_container_width=True)
            st.dataframe(ingredient_summary, hide_index=True, use_container_width=True)

    with forecast_tab:
        st.subheader("Previsão de demanda para sete dias")
        st.caption(
            "A regressão usa as vendas do período filtrado e calcula dia da semana, tendência, "
            "lag_7d, rolling_7d, início do mês e sazonalidade mensal."
        )
        forecast_daily = (
            filtered.groupby("date", as_index=False)["quantity"]
            .sum()
            .set_index("date")
            .sort_index()
        )
        complete_dates = pd.date_range(pd.Timestamp(start_date), pd.Timestamp(end_date), freq="D")
        forecast_daily = forecast_daily.reindex(complete_dates, fill_value=0)
        forecast_daily.index.name = "date"
        forecast_daily = forecast_daily.reset_index()
        if len(forecast_daily) < 56:
            st.info(
                f"Selecione um período com pelo menos 56 dias completos. "
                f"O período atual tem {len(forecast_daily)} dias."
            )
        else:
            try:
                model_module = load_forecast_module()
                test_size = max(14, int(np.ceil(len(forecast_daily) * 0.20)))
                metrics, backtest = model_module.evaluate_walk_forward(forecast_daily, test_size)
                origin_date = pd.Timestamp(forecast_daily["date"].iloc[0])
                history = forecast_daily.set_index("date")["quantity"].astype(float)
                x_all, y_all = model_module.make_training_data(history, origin_date)
                model = model_module.LinearRegression().fit(x_all, y_all)
                forecast_dates = pd.date_range(
                    forecast_daily["date"].iloc[-1] + pd.Timedelta(days=1), periods=7, freq="D"
                )
                predictions, forecast_features = model_module.predict_recursively(
                    model, history, forecast_dates, origin_date
                )
                mae = metrics["mae"]
                forecast_table = pd.DataFrame(
                    {
                        "Data": forecast_dates.date,
                        "Dia": [DAY_NAMES[date.dayofweek] for date in forecast_dates],
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
                metric_c.metric("R² no backtest", f"{metrics['r2']:.3f}")
                if metrics["mae"] > metrics["baseline_mae"]:
                    st.warning("Neste histórico, a regressão teve erro maior que repetir as vendas da semana anterior.")
                st.dataframe(forecast_table, hide_index=True, use_container_width=True)

                fig = go.Figure()
                recent_start = forecast_daily["date"].max() - pd.Timedelta(days=55)
                recent = forecast_daily[forecast_daily["date"] >= recent_start]
                recent_backtest = backtest[backtest["date"] >= recent_start]
                fig.add_trace(go.Scatter(x=recent["date"], y=recent["quantity"], mode="lines", name="Vendas reais", line={"color": "#176B87"}))
                fig.add_trace(go.Scatter(x=recent_backtest["date"], y=recent_backtest["predicted"], mode="lines", name="Backtest", line={"color": "#E07A2D", "dash": "dash"}))
                fig.add_trace(go.Scatter(x=forecast_dates, y=predictions + mae, mode="lines", line={"width": 0}, showlegend=False, hoverinfo="skip"))
                fig.add_trace(go.Scatter(x=forecast_dates, y=np.maximum(0, predictions - mae), mode="lines", line={"width": 0}, fill="tonexty", fillcolor="rgba(168,50,90,0.16)", name="Faixa indicativa ± MAE", hoverinfo="skip"))
                fig.add_trace(go.Scatter(x=forecast_dates, y=predictions, mode="lines+markers", name="Previsão 7 dias", line={"color": "#A8325A", "width": 3}))
                fig.update_layout(
                    title="Vendas reais, avaliação do modelo e previsão",
                    xaxis_title="Data",
                    yaxis_title="Pizzas",
                    hovermode="x unified",
                    legend_title="Série",
                )
                st.plotly_chart(fig, use_container_width=True)
                st.caption("A faixa previsão ± MAE é indicativa, não um intervalo de confiança. A previsão inicia no dia seguinte ao fim do período selecionado.")
            except Exception as error:
                st.error(f"Não foi possível calcular a previsão: {error}")

    with st.expander("Qualidade dos dados e interpretação"):
        st.write(
            "A fonte padrão lê diretamente as sete tabelas normalizadas em data/normalized/. "
            "A opção SQL Server consulta essas mesmas entidades no banco; CSVs de outra pizzaria "
            "passam pela normalização em memória. Categorias e ingredientes são relacionados por "
            "suas dimensões, com pizza_type_ingredients como tabela associativa. "
            "As chaves sem correspondência são excluídas dos gráficos e contabilizadas abaixo."
        )
        if source == "Enviar CSVs da pizzaria" and not apply_project_recipe_rules:
            st.markdown(
                "**Tratamento aplicado aos CSVs enviados:** categorias separadas em dimensão própria; "
                "ingredientes divididos, espaços removidos e `Artichoke` padronizado para `Artichokes`. "
                "As regras de adição de mozzarella e molho foram desmarcadas para respeitar o cardápio informado."
            )
        elif source == "Enviar CSVs da pizzaria":
            st.markdown(
                "**Tratamento aplicado aos CSVs enviados:** categorias separadas em dimensão própria; "
                "ingredientes divididos, espaços removidos, `Artichoke` padronizado para `Artichokes`, "
                "Mozzarella Cheese adicionado e Tomato Sauce incluído quando não há outro molho."
            )
        else:
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

    csv_bytes = filtered.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Baixar vendas filtradas (CSV)",
        data=csv_bytes,
        file_name="vendas_filtradas_pizzaria.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
