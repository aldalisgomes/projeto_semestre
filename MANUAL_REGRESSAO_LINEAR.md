# Manual: previsão de demanda para uma pizzaria de bairro

> **Recomendação principal: preserve tudo o que já foi feito no projeto.** A atualização está nos arquivos do modelo; o ETL, as consultas SQL, o README e os dados originais continuam como estavam. Para outra pizzaria, o único arquivo de entrada continua sendo um CSV com duas colunas: `date` e `quantity`.

## O que o modelo prevê

O script `src/02_regressao_linear_vendas_diarias.py` estima a quantidade total de pizzas vendidas em cada um dos próximos sete dias. Ele usa regressão linear supervisionada: aprende com vendas históricas e mede seu erro em datas que ficaram fora do ajuste. Além da data e da quantidade, o script calcula variáveis úteis a partir dos próprios dados; não é necessário acrescentar colunas ao CSV.

Esse primeiro modelo pode ajudar a planejar massa, compras de ingredientes, equipe e capacidade de produção. Ele prevê o total de pizzas, não o mix por sabor, tamanho ou canal.

## Dados de entrada: somente duas colunas

Prepare um CSV diário com este formato:

```csv
date,quantity
2026-10-19,42
2026-10-20,0
2026-10-21,51
```

- `date`: data local no formato `AAAA-MM-DD`.
- `quantity`: total de pizzas vendidas naquele dia.
- Inclua todos os dias do calendário, inclusive dias fechados e dias sem vendas, com `quantity=0`. O script rejeita lacunas no CSV de outra pizzaria para não adivinhar se faltou venda ou faltou registro.
- O modelo precisa de pelo menos 56 dias completos; para decisões mais estáveis, prefira 6 a 12 meses de histórico recente.
- Use sempre a mesma unidade. Não misture pizzas, pedidos, itens e valores em reais.

No projeto existente, o script continua juntando `orders.csv` e `order_details.csv` e somando `quantity` por data. Como nesses arquivos só há registros de pedidos, datas sem pedidos são completadas como zero. Para o CSV externo, preencha os zeros explicitamente.

## Variáveis que o script calcula

| Variável | Como é obtida | Uso prático |
| --- | --- | --- |
| Dia da semana | Derivado de `date` e convertido em indicadores | Aprende padrões diferentes para cada dia. |
| `time_idx` | Número de dias desde a primeira data do histórico | Capta uma tendência geral de crescimento ou queda. |
| `lag_7d` | Quantidade do mesmo dia da semana anterior | Usa a semana passada como sinal recente. |
| `rolling_7d` | Média das sete datas anteriores, sem incluir o dia previsto | Ajuda a acompanhar mudanças recentes no movimento. |
| `is_payday_week` | 1 entre os dias 1 e 10 do mês; 0 nos demais | Testa se o começo do mês se associa a uma mudança de demanda. |
| `month_sin` e `month_cos` | Duas coordenadas cíclicas calculadas a partir do mês | Representam sazonalidade sem tratar dezembro e janeiro como extremos distantes. |

O modelo não assume que a semana de pagamento sempre aumenta vendas: ele estima essa relação com os dados da loja. O indicador solicitado cobre os dias 1 a 10; outros calendários de pagamento podem exigir uma regra diferente.

As variáveis de `lag_7d` e `rolling_7d` usam apenas vendas anteriores à data prevista. Ao projetar os sete dias futuros, o script prevê um dia por vez e usa as previsões anteriores como parte do histórico. Assim, não precisa de quantidades futuras no CSV.

## Avaliação antes de usar

O script faz uma avaliação cronológica walk-forward: reserva a parte mais recente do histórico, prevê esse período em blocos de até sete dias e só incorpora vendas reais depois que cada bloco termina. Isso simula uma rotina em que a previsão é atualizada semanalmente.

Ele compara o modelo com uma referência simples: repetir a venda do mesmo dia da semana anterior (`lag_7d`). Se o MAE do modelo for maior do que o MAE dessa referência, o modelo não melhorou o método simples nesse histórico; revise os dados e não baseie compras apenas na regressão.

- **MAE**: erro absoluto médio, em pizzas por dia. Um MAE de 8 representa erro médio de aproximadamente 8 pizzas por dia no período avaliado.
- **RMSE**: erro também em pizzas, com penalidade maior para erros grandes.
- **R²**: medida de ajuste que pode ser negativa quando a previsão é pior do que usar a média do período avaliado.
- **MAE de referência**: erro de repetir a venda do mesmo dia na semana anterior.

A faixa mostrada junto à previsão é `previsão +/- MAE` observado no backtest. É uma referência operacional, não um intervalo de confiança nem uma garantia. Considere uma margem adicional em feriados, promoções, eventos e dias de alta procura.

## Gráfico

Cada execução salva `grafico_previsao_regressao_linear.png` na raiz do projeto. O gráfico apresenta as vendas reais recentes, as previsões do período de avaliação e os próximos sete dias, com uma faixa indicativa baseada no MAE. Para salvar em outro local, use `--graph-output caminho/para/grafico.png`.

## Como executar

Abra o terminal na pasta raiz do projeto e instale as dependências isoladas do modelo:

```bash
python -m pip install -r requirements-ml.txt
```

Com os dados do projeto:

```bash
python src/02_regressao_linear_vendas_diarias.py
```

Com dados de outra pizzaria:

```bash
python src/02_regressao_linear_vendas_diarias.py --daily-csv caminho/para/vendas_diarias.csv
```

Para salvar também a tabela de previsões em CSV:

```bash
python src/02_regressao_linear_vendas_diarias.py --daily-csv caminho/para/vendas_diarias.csv --output previsao_proximos_7_dias.csv
```

## Limites e próximos passos

1. O conjunto do projeto é um exemplo histórico de 2015. Para decisões reais, treine cada modelo com o histórico atual da própria pizzaria; não transfira os parâmetros aprendidos de uma loja para outra.
2. A regressão capta relações simples. Tendências, calendário de pagamento e mês podem não se repetir; acompanhe o erro mensalmente.
3. Ainda não há variáveis explícitas de feriado, clima, promoção, falta de estoque, mudança de preço, delivery ou eventos do bairro. O modelo não consegue distinguir esses motivos apenas pelas duas colunas.
4. Para prever compras por sabor ou ingredientes, o próximo passo é gerar históricos separados por produto ou categoria. A entrada diária mínima para este modelo permanece com duas colunas.
5. A sazonalidade anual é difícil de confirmar com apenas um ano de dados. Use resultados de backtest e bom senso operacional antes de alterar compras ou escala.
