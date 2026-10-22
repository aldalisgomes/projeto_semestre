"""Exporta, sem alterar os arquivos de origem, as tabelas normalizadas do projeto.

Uso na raiz do projeto:
    python src/04_exportar_base_normalizada.py

As saídas vão para data/normalized/ e são lidas diretamente pelo painel.
As regras seguem src/01_etl_and_normalization.py e 02_create_tables_reference.sql.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = SOURCE_DIR / "normalized"
VALID_SIZES = {"S", "M", "L", "XL", "XXL"}


def read_source_csv(filename: str, *, latin1_fallback: bool = False) -> pd.DataFrame:
    path = SOURCE_DIR / filename
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        if latin1_fallback:
            return pd.read_csv(path, encoding="latin1")
        raise


def require_unique_not_null(dataframe: pd.DataFrame, table: str, key: str) -> None:
    if dataframe[key].isna().any():
        raise ValueError(f"{table}.{key} contém valor nulo.")
    if dataframe[key].duplicated().any():
        raise ValueError(f"{table}.{key} contém chave duplicada.")


def build_normalized_tables() -> dict[str, pd.DataFrame]:
    orders = read_source_csv("orders.csv")
    order_details = read_source_csv("order_details.csv")
    pizzas = read_source_csv("pizzas.csv")
    source_types = read_source_csv("pizza_types.csv", latin1_fallback=True)

    # categories e pizza_types: 3FN, substituindo o texto repetido pela FK.
    categories = (
        source_types[["category"]]
        .drop_duplicates()
        .rename(columns={"category": "category_name"})
        .reset_index(drop=True)
    )
    categories["category_id"] = range(1, len(categories) + 1)
    categories = categories[["category_id", "category_name"]]
    normalized_types = source_types.merge(
        categories,
        left_on="category",
        right_on="category_name",
        how="left",
        validate="many_to_one",
    )[["pizza_type_id", "name", "category_id"]]

    # ingredients e pizza_type_ingredients: 1FN e relacionamento M:N.
    recipe_lines = source_types[["pizza_type_id", "ingredients"]].copy()
    recipe_lines["ingredients"] = recipe_lines["ingredients"].str.split(",")
    recipe_lines = recipe_lines.explode("ingredients")
    recipe_lines["ingredients"] = recipe_lines["ingredients"].str.strip()
    recipe_lines["ingredients"] = recipe_lines["ingredients"].replace(
        {"Artichoke": "Artichokes"}
    )

    # Regras de negócio documentadas pelo grupo no ETL original.
    mozzarella = pd.DataFrame(
        {"pizza_type_id": source_types["pizza_type_id"], "ingredients": "Mozzarella Cheese"}
    )
    without_other_sauce = source_types.loc[
        ~source_types["ingredients"].str.contains("Sauce", case=False), "pizza_type_id"
    ]
    tomato_sauce = pd.DataFrame(
        {"pizza_type_id": without_other_sauce, "ingredients": "Tomato Sauce"}
    )
    recipe_lines = pd.concat(
        [recipe_lines, mozzarella, tomato_sauce],
        ignore_index=True,
    ).drop_duplicates(subset=["pizza_type_id", "ingredients"])

    ingredients = (
        recipe_lines[["ingredients"]]
        .drop_duplicates()
        .rename(columns={"ingredients": "ingredient_name"})
        .reset_index(drop=True)
    )
    ingredients["ingredient_id"] = range(1, len(ingredients) + 1)
    ingredients = ingredients[["ingredient_id", "ingredient_name"]]
    pizza_type_ingredients = recipe_lines.merge(
        ingredients,
        left_on="ingredients",
        right_on="ingredient_name",
        how="left",
        validate="many_to_one",
    )[["pizza_type_id", "ingredient_id"]].drop_duplicates()

    tables = {
        "orders": orders[["order_id", "date", "time"]].copy(),
        "order_details": order_details[
            ["order_details_id", "order_id", "pizza_id", "quantity"]
        ].copy(),
        "pizzas": pizzas[["pizza_id", "pizza_type_id", "size", "price"]].copy(),
        "pizza_types": normalized_types,
        "categories": categories,
        "ingredients": ingredients,
        "pizza_type_ingredients": pizza_type_ingredients,
    }
    validate_normalized_tables(tables)
    return tables


def validate_normalized_tables(tables: dict[str, pd.DataFrame]) -> None:
    for table, key in [
        ("orders", "order_id"),
        ("order_details", "order_details_id"),
        ("pizzas", "pizza_id"),
        ("pizza_types", "pizza_type_id"),
        ("categories", "category_id"),
        ("ingredients", "ingredient_id"),
    ]:
        require_unique_not_null(tables[table], table, key)

    links = tables["pizza_type_ingredients"]
    if links[["pizza_type_id", "ingredient_id"]].isna().any().any():
        raise ValueError("pizza_type_ingredients contém chave nula.")
    if links.duplicated(["pizza_type_id", "ingredient_id"]).any():
        raise ValueError("pizza_type_ingredients contém associação duplicada.")

    orders = tables["orders"]
    details = tables["order_details"]
    pizzas = tables["pizzas"]
    types = tables["pizza_types"]
    categories = tables["categories"]
    ingredients = tables["ingredients"]

    parsed_dates = pd.to_datetime(orders["date"], errors="coerce")
    if parsed_dates.isna().any() or not parsed_dates.between("2015-01-01", "2015-12-31").all():
        raise ValueError("orders.date possui data inválida ou fora do intervalo de 2015 definido no esquema.")
    if orders["time"].isna().any():
        raise ValueError("orders.time contém valor nulo.")
    if pd.to_numeric(details["quantity"], errors="coerce").isna().any() or (
        pd.to_numeric(details["quantity"], errors="coerce") <= 0
    ).any():
        raise ValueError("order_details.quantity deve conter somente números positivos.")
    if not set(pizzas["size"].astype(str)).issubset(VALID_SIZES):
        raise ValueError("pizzas.size contém tamanho fora do padrão definido no esquema.")
    prices = pd.to_numeric(pizzas["price"], errors="coerce")
    if prices.isna().any() or (prices <= 0).any():
        raise ValueError("pizzas.price deve conter somente números positivos.")

    foreign_keys = [
        (details["order_id"], orders["order_id"], "order_details.order_id -> orders.order_id"),
        (details["pizza_id"], pizzas["pizza_id"], "order_details.pizza_id -> pizzas.pizza_id"),
        (pizzas["pizza_type_id"], types["pizza_type_id"], "pizzas.pizza_type_id -> pizza_types.pizza_type_id"),
        (types["category_id"], categories["category_id"], "pizza_types.category_id -> categories.category_id"),
        (links["pizza_type_id"], types["pizza_type_id"], "pizza_type_ingredients.pizza_type_id -> pizza_types.pizza_type_id"),
        (links["ingredient_id"], ingredients["ingredient_id"], "pizza_type_ingredients.ingredient_id -> ingredients.ingredient_id"),
    ]
    for child, parent, relationship in foreign_keys:
        if not set(child).issubset(set(parent)):
            raise ValueError(f"Chave estrangeira sem correspondência: {relationship}.")


def export_normalized_tables() -> dict[str, pd.DataFrame]:
    tables = build_normalized_tables()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for table_name, dataframe in tables.items():
        dataframe.to_csv(OUTPUT_DIR / f"{table_name}.csv", index=False, encoding="utf-8-sig")
    return tables


def main() -> None:
    tables = export_normalized_tables()
    print(f"Tabelas normalizadas exportadas para: {OUTPUT_DIR}")
    for table_name, dataframe in tables.items():
        print(f"{table_name}: {len(dataframe):,} registros")
    print("Validação de chaves, relacionamentos e regras de qualidade concluída.")


if __name__ == "__main__":
    main()
