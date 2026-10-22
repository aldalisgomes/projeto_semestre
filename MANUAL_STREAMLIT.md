# Manual do painel Streamlit — Pizza Analytics

## O que o painel entrega

O painel do Projeto Integrador IV reúne métricas úteis para a gestão de uma pizzaria: receita bruta estimada, quantidade de pizzas, pedidos, ticket médio, desempenho por categoria e tamanho, horários de maior movimento, indicadores de ingredientes associados às receitas vendidas e previsão de demanda para sete dias.

**O painel agora usa como fonte padrão as sete tabelas normalizadas pelo ETL:** `orders`, `order_details`, `pizzas`, `pizza_types`, `categories`, `ingredients` e `pizza_type_ingredients`. Elas são materializadas em `data/normalized/` e relacionadas pelas chaves e cardinalidades do modelo do grupo antes de formar os gráficos. O ETL, o esquema SQL e os CSVs originais foram preservados.

## Instalação e abertura

Na pasta raiz do projeto, instale as dependências consolidadas do projeto:

```bash
python -m pip install -r requirements.txt
```

Gere (ou atualize) as cópias normalizadas locais. O script aplica as regras e validações do projeto e grava somente em `data/normalized/`:

```bash
python src/04_exportar_base_normalizada.py
```

Depois, inicie a interface:

```bash
streamlit run src/03_streamlit_dashboard.py
```

O Streamlit abrirá o painel no navegador. Por padrão, **não analisa diretamente os CSVs desnormalizados**: lê as sete tabelas já tratadas em `data/normalized/`. A nova aba **ETL e modelo** mostra a quantidade de registros carregada de cada tabela e os relacionamentos usados nos indicadores. Para usar o banco operacional, escolha **Banco SQL Server normalizado**; essa fonte consulta diretamente as tabelas do banco por `SELECT`.

## Usar os dados de outra pizzaria

No menu lateral, escolha **Enviar CSVs da pizzaria** e forneça quatro arquivos exportados pelo sistema de vendas:

| Arquivo | Campos obrigatórios |
| --- | --- |
| `orders.csv` | `order_id`, `date`, `time` |
| `order_details.csv` | `order_id`, `pizza_id`, `quantity` |
| `pizzas.csv` | `pizza_id`, `pizza_type_id`, `size`, `price` |
| `pizza_types.csv` | `pizza_type_id`, `name`, `category` |

O campo `ingredients` em `pizza_types.csv` é opcional; sem ele, o painel mostra as demais análises e informa que a aba de ingredientes não está disponível. Quando ele existe, o painel separa a lista por vírgulas, remove espaços extras e padroniza `Artichoke` como `Artichokes`. Também separa categorias em uma dimensão própria e representa ingredientes e receitas pela dimensão `ingredients` e pela tabela associativa `pizza_type_ingredients`.

No envio de CSVs, a opção **Aplicar regras de receita do ETL deste projeto** vem marcada para reproduzir o ETL da base usada pelo grupo: incluir `Mozzarella Cheese` em todas as receitas e `Tomato Sauce` nas receitas que não indicam outro molho. Como essas duas regras podem não representar a ficha técnica de outra pizzaria, desmarque a opção se não forem verdadeiras para o cardápio enviado. Na base de exemplo local, as regras do projeto são aplicadas automaticamente. A normalização é feita em memória e não grava alterações nos arquivos.

Essas transformações não alteram os CSVs enviados nem gravam dados no banco. As chaves precisam corresponder entre os arquivos. O painel valida chaves, quantidades, preços, datas e horários; sinaliza linhas órfãs e exclui dos gráficos aquelas que não podem ser relacionadas. Datas fora de 2015 e tamanhos fora do padrão do esquema de referência são contabilizados, mas não bloqueiam a análise, para permitir históricos atuais e cardápios de outras pizzarias. Abra **Qualidade dos dados e interpretação** no painel para ver a contagem de categorias, tipos, ingredientes, relações tipo-ingrediente e as regras aplicadas. `order_details_id` é verificado quando o CSV o fornece.

A previsão de demanda do painel agrega as quantidades dos itens de venda relacionados às tabelas de pedidos e cardápio já validadas. Ingredientes não são variáveis de entrada dessa previsão: o alvo é a quantidade diária de pizzas. O algoritmo independente em `src/02_regressao_linear_vendas_diarias.py` continua podendo receber somente `date,quantity`, como descrito em `MANUAL_REGRESSAO_LINEAR.md`.

## Conectar ao SQL Server

O painel também oferece a opção **Banco SQL Server**. Essa conexão faz somente consultas `SELECT` ao esquema normalizado `PizzaSales`; o painel não grava nem altera dados.

Configure `PIZZA_DATABASE_URL` antes de iniciar o Streamlit. Exemplo no PowerShell, substituindo os marcadores pelos dados locais:

```powershell
$env:PIZZA_DATABASE_URL = "mssql+pyodbc://USUARIO:SENHA@localhost:1433/PizzaSales?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes"
streamlit run src/03_streamlit_dashboard.py
```

Se a senha tiver caracteres reservados em uma URL, codifique-os para URL. O driver ODBC do SQL Server precisa estar instalado na máquina. Não coloque senhas no código nem em arquivos versionados.

## Como ler os resultados

- **Receita bruta** usa preço de venda multiplicado pela quantidade. O seletor de moeda altera apenas o símbolo; não converte valores. A base pública de exemplo tem preços em dólares.
- **Ticket médio** é receita bruta dividida pelo número de pedidos distintos no período.
- **Picos de demanda** usa a data e a hora registradas no pedido. Ajuda a visualizar períodos movimentados, mas não mede tempo de preparo ou capacidade real da cozinha.
- **Ingredientes** conta pizzas vendidas cujas receitas listam cada ingrediente. Um mesmo ingrediente pode aparecer em receitas de muitas pizzas; esse indicador não equivale a gramas, estoque ou custo consumido.
- **Previsão** usa o modelo de regressão existente, requer pelo menos 56 dias no intervalo selecionado e compara o erro com repetir a venda do mesmo dia da semana anterior (`lag_7d`). A previsão começa no dia seguinte ao fim do intervalo.

## Por que os gráficos podem continuar com números parecidos

A normalização reorganiza os dados em sete tabelas relacionadas e reduz repetição e inconsistências de cadastro. Ela não deveria alterar a quantidade de pizzas vendidas nem a receita quando as chaves e os valores estão corretos. Por isso, indicadores agregados como vendas por dia, receita ou pizzas por categoria podem manter os mesmos resultados: o painel reconstrói essas métricas por meio dos relacionamentos entre as tabelas normalizadas. A diferença principal está na estrutura, na integridade e na possibilidade de analisar categorias e ingredientes com relacionamentos consistentes; não em mudar artificialmente os números da operação. A aba **ETL e modelo** evidencia as tabelas, seus volumes e os relacionamentos usados.

## Limites para apresentar o projeto

A base do projeto é uma amostra histórica de 2015. Ela serve para demonstrar o pipeline e o painel, não para orientar compras atuais. Cada pizzaria precisa carregar seus próprios dados recentes.

A base contém preços e vendas, mas não contém custo por ingrediente, quantidade de ingrediente por receita, desperdício, descontos detalhados ou custo de mão de obra. Portanto, o painel calcula **receita bruta**, não lucro ou margem de contribuição. Para responder à pergunta de rentabilidade real levantada na conversa com a pizzaria, seria necessário cadastrar fichas técnicas com gramagem, custo atualizado dos insumos e outros custos operacionais.
