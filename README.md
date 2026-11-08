# Painel de Análise de Dados para Pizzarias

Projeto Integrador IV da UNIVESP, desenvolvido em Python, SQL e Streamlit. O trabalho começou com o conjunto público **Pizza Place Sales**, utilizado para construir a modelagem relacional, o ETL, as consultas SQL e as análises. Depois, o painel foi ampliado para importar arquivos CSV de outros estabelecimentos. O estudo de caso da pizzaria de bairro demonstra essa extensão.

As fontes são independentes: o conjunto público descreve vendas fictícias de 2015; o arquivo `VENDAS_PIZZARIA_BAIRRO.csv` contém dados reais do estabelecimento de estudo, com a identidade comercial omitida. O CSV comercial permanece local e não deve ser publicado sem autorização.

## Objetivo e etapas

1. Inspecionar e organizar dados públicos de pedidos, itens, produtos e receitas.
2. Normalizar o esquema em sete tabelas, implementar ETL e consultas SQL analíticas.
3. Apresentar indicadores, gráficos, filtros e previsão diária no Streamlit.
4. Permitir a importação guiada de dados de outras pizzarias, com diagnóstico de qualidade, calendário configurável e análises habilitadas conforme os campos disponíveis.

## Fontes de dados

| Fonte | Uso | Período e características |
| --- | --- | --- |
| Pizza Place Sales | Desenvolvimento e análises originais de SQL/ETL | 2015; quatro arquivos brutos e 48.620 linhas de itens. O desafio descreve um estabelecimento fictício. A página do Maven Data Playground lista a licença como Public Domain. |
| `VENDAS_PIZZARIA_BAIRRO.csv` | Estudo de caso de aplicação em estabelecimento externo | 01/08/2026 a 30/09/2026; CSV local de vendas reais, com nome comercial omitido. Não é a base pública. |
| CSV enviado pelo usuário | Análise personalizada | Período, cardápio e funcionamento dependem do arquivo e da configuração informada pelo usuário. |

Referências da base pública: [Maven Pizza Challenge](https://mavenanalytics.io/challenges/maven-pizza-challenge) e [Pizza Place Sales — Maven Data Playground](https://status.mavenanalytics.io/data-playground/pizza-place-sales). Confira a licença e os termos na fonte antes de redistribuir os arquivos.

## Modelagem, ETL e análises

O esquema relacional contém `orders`, `order_details`, `pizzas`, `pizza_types`, `categories`, `ingredients` e `pizza_type_ingredients`. A lista de ingredientes é decomposta em registros atômicos (1FN); categorias e ingredientes usam dimensões e chaves estrangeiras para reduzir repetição. O esquema público conserva as restrições ligadas ao conjunto de 2015, inclusive os tamanhos S, M, L, XL e XXL.

O ETL lê os quatro CSVs públicos, trata nomes e relações de ingredientes, audita campos e chaves, cria o esquema e carrega o SQL Server. O exportador também gera sete CSVs normalizados em `data/normalized/`, usados pelo painel e pelo adaptador SQLite em memória quando o SQL Server não está disponível.

As consultas em `03_analysis_queries.sql` demonstram filtros, `JOIN`s, agregações, subconsultas, operações de conjuntos, CTEs, função de janela, autojunção e `HAVING`. São consultas da base pública; o CSV externo não é redirecionado para esse esquema.

Os indicadores comerciais derivam de somas e agrupamentos por pedido, produto, categoria, tamanho, data, dia da semana e horário. Receita bruta é `Σ(quantidade × preço unitário)`; não representa lucro. A análise de ingredientes associa vendas à lista de ingredientes cadastrada, mas não estima gramagem, custo ou consumo físico.

A previsão existente usa regressão linear com variáveis de calendário e histórico (`weekday`, índice temporal, `lag_7d`, média móvel de sete dias, indicador do início do mês e componentes cíclicos mensais). A avaliação cronológica usa MAE, RMSE, R² e comparação com a referência `lag_7d`. O painel exige 56 dias completos para treinar e apresenta sete dias futuros; a faixa `previsão ± MAE` é indicativa, não intervalo de confiança. 

## Aplicação Streamlit

O painel separa a base pública, o estudo de caso, a importação de um CSV, o envio de quatro tabelas relacionais e a conexão somente para leitura ao SQL Server. As abas incluem visão geral, cardápio, picos de demanda, ingredientes, previsão, avaliação do modelo, consultas SQL e fontes de dados. Títulos e indicadores identificam a fonte selecionada.

URL de demonstração registrada nos materiais do projeto: [painel-pizzaria.streamlit.app](https://painel-pizzaria.streamlit.app/). A  demonstração publicada deve usar a base pública ou um CSV carregado pelo usuário.

No CSV simples, `data` e `quantidade` são necessários para a série de vendas; as análises de pedidos, receita, produtos, categorias, tamanhos, horários e ingredientes dependem dos respectivos campos. O diagnóstico sinaliza datas inválidas, valores numéricos, cabeçalhos, pedidos inconsistentes, linhas aparentemente repetidas e lacunas de calendário. Linhas repetidas são apenas avisadas: não há exclusão automática. Dias fechados e dias abertos sem vendas são tratados segundo o calendário e a confirmação do responsável.

### Estrutura principal

```text
.
├── data/                         # CSVs públicos e tabelas normalizadas
├── docs/                         # Modelo de CSV, dicionário e relatórios de teste
├── docker/docker-compose.yml     # Serviço SQL Server
├── src/
│   ├── 01_etl_and_normalization.py
│   ├── 02_regressao_linear_vendas_diarias.py
│   ├── 03_streamlit_dashboard.py
│   ├── 04_exportar_base_normalizada.py
│   └── pizzeria_import.py
├── tests/                        # Testes do importador e da interface
├── 02_create_tables_reference.sql
├── 03_analysis_queries.sql
├── Dockerfile
├── Makefile
├── requirements.txt
```

O arquivo local `output/VENDAS_PIZZARIA_BAIRRO.csv`,  backups e configurações `.env` são ignorados pelo Git. A aplicação em modo de estudo de caso exige que o CSV esteja nesse caminho local. Em Docker, `make dashboard-docker` monta `output/` como volume somente leitura, sem copiar os dados comerciais para a imagem.

## Instalação e execução no Windows

Abra PowerShell comum na raiz do repositório; não é necessário executá-lo como administrador.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run src/03_streamlit_dashboard.py
```

O comando `python -m streamlit` executa pelo interpretador do ambiente virtual. Abra o endereço local informado no terminal (normalmente `http://localhost:8501`) e encerre com `Ctrl+C`. Para usar SQL Server, configure as variáveis de ambiente descritas no manual; para usar a base normalizada em CSV/SQLite, não é necessário configurar credenciais.

## Docker e Makefile

O serviço SQL Server é executado em container e persiste seus dados no volume `vesuvio_sqlserver_data`. O `Dockerfile` monta a imagem Python usada pelo ETL e pelo painel; o Streamlit pode ser executado dentro de um container efêmero conectado à rede do Compose. O serviço e o painel se comunicam pela rede Compose; a porta 1433 é publicada para acesso local e o painel expõe 8501.

O Makefile usa GNU Make, Bash, Docker Engine/Compose v2 e, no Windows, WSL2 com integração ao Docker Desktop. Antes de usar SQL Server, copie `.env.example` para `.env`, substitua a senha de exemplo e ajuste as URLs. O `.env` não é versionado.

Alvos existentes: `help`, `setup`, `db-up`, `db-down`, `run`, `normalize`, `dashboard`, `dashboard-docker`, `all` e `clean`. `make run` e `make all` executam o ETL demonstrativo, que recria o banco `PizzaSales`; não use essa carga em um banco de produção. `make clean` apaga somente os caches `__pycache__`. Detalhes e pré-requisitos estão no manual.

## CSV para outras pizzarias

Baixe o [modelo CSV](docs/modelo_csv_vendas_pizzaria.csv) e leia o [dicionário de campos](docs/modelo_csv_vendas_pizzaria.md). O cabeçalho de referência é:

```csv
data,quantidade,pedido_id,hora,produto,tamanho,preco_unitario,categoria,ingredientes
```

Datas ISO (`AAAA-MM-DD`) são preferidas; datas brasileiras (`DD/MM/AAAA`) também são aceitas quando identificáveis sem ambiguidade. `quantidade` deve ser inteira e positiva nas linhas comerciais; não use linhas comerciais de quantidade zero para representar fechamento. Repita `pedido_id` quando um pedido contiver diferentes itens. Preços devem ser numéricos e unitários. O painel permite configurar calendário e funcionamento por estabelecimento.

## Testes e limitações

Com as dependências instaladas:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

A avaliação da previsão depende de pelo menos 56 dias válidos. Feriados, promoções, custos, margens, desperdício e capacidade de produção não estão representados pelo modelo. A configuração e execução Docker precisam do serviço Docker ativo.

