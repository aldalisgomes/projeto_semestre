"""Previsão de demanda diária com regressão linear e histórico de vendas.

Entrada de outras pizzarias: CSV com apenas date e quantity (uma linha por dia).
As variáveis de calendário e histórico são calculadas pelo próprio programa.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEEKDAY_NAMES = [
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
]
WEEKDAY_FEATURES = [f"weekday_{day}" for day in range(1, 7)]
FEATURE_COLUMNS = [
    *WEEKDAY_FEATURES,
    "time_idx",
    "lag_7d",
    "rolling_7d",
    "is_payday_week",
    "month_sin",
    "month_cos",
]
MIN_HISTORY_DAYS = 56


def load_daily_sales(daily_csv: Path | None) -> tuple[pd.DataFrame, int]:
    """Carrega vendas diárias; retorna também quantas datas foram completadas."""
    using_project_data = daily_csv is None
    if daily_csv is not None:
        daily_csv = daily_csv.expanduser().resolve()
        if not daily_csv.is_file():
            raise FileNotFoundError(f"Arquivo CSV não encontrado: {daily_csv}")

        daily = pd.read_csv(daily_csv)
        required = {"date", "quantity"}
        missing_columns = required.difference(daily.columns)
        if missing_columns:
            raise ValueError(
                "O CSV precisa ter somente os campos necessários 'date' e 'quantity'. "
                f"Colunas ausentes: {', '.join(sorted(missing_columns))}"
            )
    else:
        orders_path = PROJECT_ROOT / "data" / "normalized" / "orders.csv"
        details_path = PROJECT_ROOT / "data" / "normalized" / "order_details.csv"
        if not orders_path.is_file() or not details_path.is_file():
            raise FileNotFoundError(
                "Não encontrei data/normalized/orders.csv e "
                "data/normalized/order_details.csv. Gere as tabelas tratadas com "
                "'python src/04_exportar_base_normalizada.py' ou informe um CSV diário "
                "com --daily-csv."
            )

        orders = pd.read_csv(orders_path, usecols=["order_id", "date"])
        details = pd.read_csv(details_path, usecols=["order_id", "quantity"])
        joined = details.merge(orders, on="order_id", how="inner", validate="many_to_one")
        daily = joined.groupby("date", as_index=False)["quantity"].sum()

    daily = daily[["date", "quantity"]].copy()
    daily["date"] = pd.to_datetime(daily["date"], errors="coerce").dt.normalize()
    daily["quantity"] = pd.to_numeric(daily["quantity"], errors="coerce")
    invalid = daily[["date", "quantity"]].isna().any(axis=1)
    if invalid.any():
        raise ValueError(f"Há {int(invalid.sum())} linha(s) sem data ou quantidade válida.")
    if daily.empty:
        raise ValueError("Não há linhas com data e quantidade para treinar o modelo.")
    if (daily["quantity"] < 0).any():
        raise ValueError("A quantidade vendida não pode ser negativa.")

    # Consolida registros repetidos do mesmo dia antes de calcular as defasagens.
    daily = daily.groupby("date", as_index=False)["quantity"].sum().sort_values("date")
    calendar = pd.date_range(daily["date"].min(), daily["date"].max(), freq="D")
    existing_dates = pd.DatetimeIndex(daily["date"])
    missing_dates = calendar.difference(existing_dates)

    if len(missing_dates) and not using_project_data:
        examples = ", ".join(str(day.date()) for day in missing_dates[:5])
        raise ValueError(
            f"O CSV tem {len(missing_dates)} data(s) sem linha (por exemplo: {examples}). "
            "Inclua todos os dias; use quantity=0 quando não houve venda ou a loja ficou fechada."
        )

    if using_project_data and len(missing_dates):
        # No CSV de pedidos, uma data sem nenhum pedido é uma venda diária igual a zero.
        daily = (
            daily.set_index("date")
            .reindex(calendar, fill_value=0)
            .rename_axis("date")
            .reset_index()
        )

    return daily.reset_index(drop=True), len(missing_dates)


def make_calendar_features(dates: pd.DatetimeIndex, origin_date: pd.Timestamp) -> pd.DataFrame:
    """Cria variáveis de calendário a partir das datas, sem dados externos."""
    dates = pd.DatetimeIndex(dates)
    weekdays = pd.Series(pd.Categorical(dates.dayofweek, categories=range(7)))
    weekday_features = pd.get_dummies(
        weekdays, prefix="weekday", drop_first=True, dtype=float
    ).reindex(columns=WEEKDAY_FEATURES, fill_value=0.0)
    weekday_features.index = dates

    month_angle = 2 * np.pi * (dates.month - 1) / 12
    weekday_features["time_idx"] = (dates - pd.Timestamp(origin_date)).days.astype(float)
    weekday_features["is_payday_week"] = (dates.day <= 10).astype(float)
    weekday_features["month_sin"] = np.sin(month_angle)
    weekday_features["month_cos"] = np.cos(month_angle)
    return weekday_features


def make_training_data(
    history: pd.Series, origin_date: pd.Timestamp
) -> tuple[pd.DataFrame, pd.Series]:
    """Monta linhas de treino usando somente vendas anteriores à data prevista."""
    features = make_calendar_features(pd.DatetimeIndex(history.index), origin_date)
    features["lag_7d"] = history.shift(7).to_numpy()
    features["rolling_7d"] = history.shift(1).rolling(window=7, min_periods=7).mean().to_numpy()
    target = history.rename("quantity")
    usable = features.join(target).dropna()
    return usable[FEATURE_COLUMNS], usable["quantity"]


def predict_recursively(
    model: LinearRegression,
    history: pd.Series,
    dates: pd.DatetimeIndex,
    origin_date: pd.Timestamp,
) -> tuple[np.ndarray, pd.DataFrame]:
    """Prevê dias em sequência e usa previsões anteriores dentro do horizonte."""
    working_history = history.astype(float).copy()
    predictions: list[float] = []
    used_features: list[pd.Series] = []

    for date in pd.DatetimeIndex(dates):
        lag_date = date - pd.Timedelta(days=7)
        rolling_dates = pd.date_range(date - pd.Timedelta(days=7), periods=7, freq="D")
        if lag_date not in working_history.index or not rolling_dates.isin(working_history.index).all():
            raise ValueError("O histórico precisa conter todos os dias anteriores à previsão.")

        row = make_calendar_features(pd.DatetimeIndex([date]), origin_date)
        row["lag_7d"] = float(working_history.loc[lag_date])
        row["rolling_7d"] = float(working_history.loc[rolling_dates].mean())
        row = row[FEATURE_COLUMNS]
        prediction = max(float(model.predict(row)[0]), 0.0)
        predictions.append(prediction)
        used_features.append(row.iloc[0])
        working_history.loc[date] = prediction

    feature_frame = pd.DataFrame(used_features, index=pd.DatetimeIndex(dates))
    return np.asarray(predictions), feature_frame


def evaluate_walk_forward(
    daily: pd.DataFrame, test_size: int
) -> tuple[dict[str, float], pd.DataFrame]:
    """Avalia em blocos semanais sem usar vendas futuras como entrada do modelo."""
    origin_date = pd.Timestamp(daily["date"].iloc[0])
    split_at = len(daily) - test_size
    initial_history = daily.iloc[:split_at].set_index("date")["quantity"].astype(float)
    test = daily.iloc[split_at:].reset_index(drop=True)
    history = initial_history.copy()
    predictions: list[float] = []
    baselines: list[float] = []

    for start in range(0, len(test), 7):
        block = test.iloc[start : start + 7]
        x_train, y_train = make_training_data(history, origin_date)
        model = LinearRegression().fit(x_train, y_train)
        block_dates = pd.DatetimeIndex(block["date"])
        block_predictions, _ = predict_recursively(model, history, block_dates, origin_date)
        predictions.extend(block_predictions.tolist())
        baselines.extend(
            float(history.loc[date - pd.Timedelta(days=7)]) for date in block_dates
        )

        # Após cada semana, a avaliação considera que as vendas reais já foram observadas.
        actual_block = block.set_index("date")["quantity"].astype(float)
        history = pd.concat([history, actual_block])

    actual = test["quantity"].to_numpy(dtype=float)
    predictions_array = np.asarray(predictions)
    baseline_array = np.asarray(baselines)
    metrics = {
        "mae": float(mean_absolute_error(actual, predictions_array)),
        "rmse": float(np.sqrt(mean_squared_error(actual, predictions_array))),
        "r2": float(r2_score(actual, predictions_array)),
        "baseline_mae": float(mean_absolute_error(actual, baseline_array)),
    }
    backtest = pd.DataFrame(
        {"date": test["date"], "actual": actual, "predicted": predictions_array}
    )
    return metrics, backtest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prevê as vendas diárias dos próximos sete dias usando as colunas date e quantity."
    )
    parser.add_argument(
        "--daily-csv",
        type=Path,
        help="Arquivo CSV diário com as colunas date e quantity. Se omitido, usa os dados atuais do projeto.",
    )
    parser.add_argument("--output", type=Path, help="Opcional: caminho para salvar a tabela de previsão em CSV.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    daily, filled_days = load_daily_sales(args.daily_csv)
    if filled_days:
        if args.daily_csv is None:
            print(
                f"Datas sem pedidos na base original preenchidas com zero: {filled_days}."
            )

    if len(daily) < MIN_HISTORY_DAYS:
        raise ValueError(
            f"São necessários pelo menos {MIN_HISTORY_DAYS} dias completos de histórico "
            "para treinar e avaliar este modelo com defasagens semanais."
        )

    test_size = max(14, int(np.ceil(len(daily) * 0.20)))
    if len(daily) - test_size < 35:
        raise ValueError("O período de treino precisa ter pelo menos 35 dias completos.")

    metrics, _ = evaluate_walk_forward(daily, test_size)
    origin_date = pd.Timestamp(daily["date"].iloc[0])
    full_history = daily.set_index("date")["quantity"].astype(float)
    x_all, y_all = make_training_data(full_history, origin_date)
    final_model = LinearRegression().fit(x_all, y_all)

    forecast_dates = pd.date_range(daily["date"].iloc[-1] + pd.Timedelta(days=1), periods=7, freq="D")
    forecast, forecast_features = predict_recursively(
        final_model, full_history, forecast_dates, origin_date
    )
    mae = metrics["mae"]
    forecast_table = pd.DataFrame(
        {
            "date": forecast_dates.date,
            "day_of_week": [WEEKDAY_NAMES[date.dayofweek] for date in forecast_dates],
            "lag_7d": np.rint(forecast_features["lag_7d"].to_numpy()).astype(int),
            "rolling_7d": np.round(forecast_features["rolling_7d"].to_numpy(), 1),
            "predicted_pizzas": np.rint(forecast).astype(int),
            "indicative_low": np.maximum(0, np.floor(forecast - mae)).astype(int),
            "indicative_high": np.ceil(forecast + mae).astype(int),
        }
    )

    print(f"Dias no histórico: {len(daily)} ({daily['date'].min().date()} a {daily['date'].max().date()})")
    print(f"Treinamento com validação progressiva: {len(daily) - test_size} dias | avaliação: {test_size} dias")
    print("\nVariáveis calculadas a partir de date e quantity:")
    print("  dia da semana, tendência (time_idx), lag_7d, rolling_7d,")
    print("  semana de pagamento (dias 1 a 10) e sazonalidade mensal (month_sin/month_cos).")
    print("\nDesempenho na avaliação cronológica:")
    print(f"  MAE do modelo: {metrics['mae']:.2f} pizzas/dia")
    print(f"  RMSE: {metrics['rmse']:.2f} pizzas/dia")
    print(f"  R²: {metrics['r2']:.3f}")
    print(f"  MAE de referência (mesmo dia da semana anterior): {metrics['baseline_mae']:.2f} pizzas/dia")
    if metrics["mae"] > metrics["baseline_mae"]:
        print("  Atenção: neste histórico, o modelo errou mais que a referência lag_7d.")

    print("\nPrevisão para os próximos sete dias:")
    print("(faixa indicativa = previsão +/- MAE da avaliação; não é intervalo de confiança)")
    display_table = forecast_table.rename(
        columns={
            "date": "Data",
            "day_of_week": "Dia da semana",
            "lag_7d": "Venda na semana anterior",
            "rolling_7d": "Média móvel de 7 dias",
            "predicted_pizzas": "Previsão de pizzas",
            "indicative_low": "Limite inferior indicativo",
            "indicative_high": "Limite superior indicativo",
        }
    )
    print(display_table.to_string(index=False))

    if args.output:
        output_path = args.output.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        forecast_table.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"Previsões salvas em: {output_path}")


if __name__ == "__main__":
    main()
