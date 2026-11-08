# Modelo de CSV para vendas de pizzarias

O arquivo `modelo_csv_vendas_pizzaria.csv` é um exemplo genérico para preparar dados para o painel. Os nomes e valores nas linhas são fictícios e servem somente como exemplo de formato.

## Colunas

| Coluna | Obrigatória | Descrição |
| --- | --- | --- |
| `data` | Sim | Data da venda. Prefira `AAAA-MM-DD`, como `2026-01-15`. |
| `quantidade` | Sim | Número inteiro positivo de unidades na linha. Não use zero em uma linha comercial para representar dia sem venda ou fechado. |
| `pedido_id` | Não | Identificador do pedido. Repita o mesmo identificador nas linhas de itens do mesmo pedido. Sem ele, não há contagem de pedidos nem ticket médio. |
| `hora` | Não | Horário registrado para o item/pedido, preferencialmente `HH:MM`. |
| `produto` | Não | Nome do produto ou sabor, conforme o cardápio do próprio estabelecimento. |
| `tamanho` | Não | Tamanho usado pela pizzaria; não há lista fixa exigida. |
| `preco_unitario` | Não | Preço de uma unidade, não o total da linha. O painel não converte moedas. |
| `categoria` | Não | Categoria definida pelo estabelecimento. |
| `ingredientes` | Não | Ingredientes separados por vírgula ou ponto e vírgula. A análise não estima gramagem ou consumo físico. |

Cada registro deve representar um item vendido; `quantidade` informa quantas unidades daquele item pertencem ao pedido. A mesma venda pode ocupar mais de uma linha se o pedido contiver diferentes produtos.

O painel também reconhece nomes equivalentes como `date`, `data_venda`, `quantity`, `order_id`, `id_pedido`, `time`, `product`, `produto_nome`, `size`, `unit_price`/`price`/`preco`, `category` e `ingredients`, além de aliases em português. O mapeamento sugerido deve ser revisado e confirmado no Streamlit; colunas desconhecidas não são usadas sem escolha explícita.

Para a previsão, a série diária é completada entre a primeira e a última data. Dias configurados como fechados recebem zero. Dias abertos sem linha permanecem desconhecidos até que o usuário confirme que representam zero vendas; sem confirmação, a previsão não é executada. Esses zeros existem somente na série temporal e não criam registros transacionais. O CSV original e as linhas aparentemente duplicadas permanecem intactos.
