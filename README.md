# Vendas da Pizzaria — fluxo de dados e análises

[![Python](https://img.shields.io/badge/Python-3.10-blue.svg)](https://www.python.org/)
[![SQL Server](https://img.shields.io/badge/SQL_Server-2022-red.svg)](https://www.microsoft.com/en-us/sql-server)
[![Docker](https://img.shields.io/badge/Docker-Habilitado-blue.svg)](https://www.docker.com/)

**Repositório:** https://github.com/aldalisgomes/projeto_semestre

## Visão geral

Este estudo de caso apresenta um fluxo completo de dados para uma pizzaria fictícia: parte de arquivos CSV desnormalizados, organiza os dados em um banco relacional e disponibiliza análises para apoiar decisões do negócio.

O objetivo principal é reestruturar um banco com redundâncias e anomalias de atualização. Para isso, o projeto:

1. Aplica a Primeira e a Terceira Forma Normal (1FN e 3FN) e regras de limpeza.
2. Automatiza a carga de dados no SQL Server usando Python, Pandas e SQLAlchemy.
3. Disponibiliza análises de negócio em SQL e em um painel Streamlit.

## Tecnologias e ferramentas

- **Linguagens:** Python e T-SQL.
- **Bibliotecas:** Pandas, SQLAlchemy e PyODBC.
- **Banco de dados:** Microsoft SQL Server em contêiner.
- **Infraestrutura:** Docker e Docker Compose.
- **Automação:** Makefile.
- **Modelagem:** notações de Peter Chen e pé de galinha (Crow's Foot).

## Estrutura do projeto

~~~text
projeto_semestre/
├── data/
│   ├── data_dictionary.csv
│   ├── order_details.csv
│   ├── orders.csv
│   ├── pizza_types.csv
│   ├── pizzas.csv
│   └── normalized/                 # sete tabelas exportadas pelo ETL
├── docker/
│   └── docker-compose.yml
├── src/
│   ├── 01_etl_and_normalization.py
│   ├── 02_regressao_linear_vendas_diarias.py
│   ├── 03_streamlit_dashboard.py
│   └── 04_exportar_base_normalizada.py
├── 02_create_tables_reference.sql
├── 03_analysis_queries.sql
├── Dockerfile
├── Makefile
├── MANUAL_REGRESSAO_LINEAR.md
├── MANUAL_STREAMLIT.md
├── README.md
└── requirements.txt
~~~

## Modelo relacional e normalização

### Processo de normalização

- **Primeira Forma Normal (1FN):** a base original armazenava vários ingredientes em uma única coluna, separados por vírgulas. O projeto separa esses valores e cria a tabela associativa pizza_type_ingredients.
- **Terceira Forma Normal (3FN):** as categorias de pizza eram repetidas como texto. O projeto as move para a tabela categories e relaciona pizza_types por uma chave estrangeira.

### Limpeza e regras de negócio

O tratamento em Python aplica as seguintes regras à base de demonstração:

- Remove espaços excedentes dos nomes de ingredientes.
- Padroniza Artichoke como Artichokes.
- Adiciona Mozzarella Cheese às receitas.
- Adiciona Tomato Sauce somente às receitas originais que não indicam outro molho.
- Remove associações duplicadas entre tipos de pizza e ingredientes.

Essas regras foram definidas para a base usada no projeto. Ao enviar dados de outra pizzaria, a interface permite desativar as regras de receita que não correspondam ao cardápio local.

### Diagrama de relacionamento entre entidades

~~~text
[ categories ]
      │ (1)
      │
      └───────< (N) [ pizza_types ] ───(1)───────< (N) [ pizzas ]
                         │                                  │ (1)
                         │ (1)                              │
                         │                                  └───────< (N) [ order_details ]
                         └───────< (N)                                         │ (N)
                                    [ pizza_type_ingredients ]                 │
                         ┌───────< (N)                                         │
                         │ (1)                                                 │ (1)
                  [ ingredients ]                                         [ orders ]
~~~

## Como executar o projeto

### 1. Pré-requisitos

O grupo validou o fluxo completo no Windows, usando WSL2 Ubuntu, Docker Desktop com integração WSL, GNU Make, VS Code e navegador.

Nesse ambiente, instale e inicie o Docker Desktop no Windows, habilite a distribuição Ubuntu nas configurações de integração WSL do Docker Desktop e instale Git e GNU Make dentro do Ubuntu. O VS Code é opcional.

O projeto também foi preparado para Linux nativo em computador Intel/AMD x86-64. Esse caminho requer Git, GNU Make, Bash, Docker Engine e o complemento Docker Compose v2. O grupo não testou o projeto em uma máquina Linux nativa. A Microsoft oferece suporte a contêineres Linux do SQL Server em computadores x86-64; emulação ARM não é um substituto compatível. Consulte as [notas de versão do SQL Server para Linux](https://learn.microsoft.com/en-us/sql/linux/sql-server-linux-release-notes?view=sql-server-ver16) e a [instalação do Docker Compose no Linux](https://docs.docker.com/compose/install/linux/).

No fluxo Docker, Python e ODBC são instalados na imagem da aplicação, não no WSL ou Linux do computador. O painel local exige as dependências Python e, para conectar ao SQL Server, o driver ODBC do sistema. Azure Data Studio, SSMS e a extensão SQL Server do VS Code são ferramentas opcionais: o painel Streamlit também exibe as consultas e seus resultados.

### 2. Clonar o repositório

Abra o Ubuntu do WSL no Windows ou um terminal Linux e execute:

~~~bash
git clone https://github.com/aldalisgomes/projeto_semestre
cd projeto_semestre
~~~

### 3. Iniciar o SQL Server

Na raiz do repositório, use o Makefile para iniciar o contêiner do banco:

~~~bash
make db-up
~~~

O Docker Compose cria a rede vesuvio_default e inicia o SQL Server na porta 1433. O Makefile aguarda o banco ficar pronto antes de encerrar o comando.

### 4. Executar o fluxo ETL (extração, transformação e carga)

O comando constrói a imagem Python e executa o pipeline ETL. O processo audita os dados, aplica as regras de limpeza e normalização e carrega as tabelas no SQL Server:

~~~bash
make run
~~~

Acompanhe a auditoria e as mensagens de carga no terminal. O fluxo completo de demonstração, da inicialização do banco até a abertura do painel, pode ser executado com make all.

### 5. Validar os dados e consultar as análises

Depois do ETL, a aba **Consultas SQL** do painel permite executar as consultas e conferir os resultados. Um cliente SQL separado é opcional. Se preferir usá-lo, escolha uma das opções a seguir.

**Opção A: Azure Data Studio ou SSMS**

1. Abra o Azure Data Studio, o SQL Server Management Studio (SSMS) ou outro cliente SQL.
2. Conecte-se usando:
   - Servidor: localhost,1433
   - Usuário: sa
   - Senha: SenhaForte@2026!
   - Banco de dados: PizzaSales
3. Abra o arquivo 03_analysis_queries.sql e execute as consultas para avaliar junções, subconsultas, operações de conjuntos e outras regras de negócio.

**Opção B: VS Code (opcional)**

1. No Ubuntu do WSL, entre na pasta clonada e abra o VS Code com o comando code . No Linux, abra a pasta do projeto pelo próprio VS Code ou pelo terminal.
2. Instale a extensão oficial SQL Server (mssql) da Microsoft.
3. Abra a paleta de comandos com Ctrl+Shift+P ou F1 e escolha **MS SQL: Add Connection** (adicionar conexão do MS SQL).
4. Preencha os dados:
   - Nome do perfil: um nome de sua escolha, como Pizza Local.
   - Servidor: localhost,1433.
   - Tipo de autenticação: SQL Login (autenticação SQL).
   - Usuário: sa.
   - Senha: SenhaForte@2026!.
   - Banco de dados: PizzaSales.
   - Trust server certificate (confiar no certificado do servidor): Sim.
5. Abra 03_analysis_queries.sql, selecione a consulta desejada e pressione Ctrl+Shift+E. Os resultados aparecem no painel lateral.

### 6. Encerrar os contêineres

Quando terminar, pare e remova o contêiner do SQL Server e a rede, e limpe os arquivos temporários do Python:

~~~bash
make db-down
make clean
~~~

make db-down preserva o volume nomeado do Docker, que contém os arquivos do banco. O comando não apaga a pasta clonada do projeto. Execute make help para ver todos os alvos disponíveis.

### 7. Abrir o painel e usar os comandos do Makefile

O fluxo completo validado pelo grupo foi executado no Windows + WSL2 Ubuntu + Docker Desktop com integração WSL + GNU Make. Em Linux nativo x86-64, use Docker Engine e Docker Compose v2 no lugar do Docker Desktop. O VS Code é opcional.

No fluxo Docker, o Makefile inicia o Streamlit em modo sem interface gráfica para evitar a tentativa de abrir um navegador Linux no WSL. Ele aguarda a porta 8501 responder e abre o navegador padrão do Windows. No Linux com ambiente gráfico, tenta abrir o navegador disponível. Sem interface gráfica, acesse manualmente http://localhost:8501. O grupo validou o caminho WSL; não testou uma instalação Linux nativa.

~~~bash
make help                 # lista os comandos disponíveis
make setup                # cria o ambiente .venv e instala requirements.txt
make normalize            # atualiza as sete tabelas em data/normalized/
make dashboard            # atualiza os CSVs e abre o painel local na porta 8501
make dashboard-docker     # abre o painel em contêiner Docker
make all                  # banco + ETL + tabelas normalizadas + painel Docker
~~~

make dashboard usa Python instalado localmente e tenta conectar ao SQL Server por PIZZA_DATABASE_URL. Se a conexão não estiver disponível, o painel usa os CSVs normalizados locais. make dashboard-docker exporta os CSVs dentro de um contêiner e executa o painel sem exigir Python ou ODBC no WSL/Linux. Para carregar o banco SQL Server de demonstração, execute make run ou make all.

**Atenção:** o ETL executa o DDL de referência, que apaga e recria o banco PizzaSales. Use make run e make all somente em ambiente de demonstração ou teste. Eles não são necessários para abrir o painel usando os CSVs normalizados locais.

Na aba **Consultas SQL**, o painel lê as consultas numeradas de 03_analysis_queries.sql, exibe o código selecionado e mostra os resultados. Com SQL Server conectado, executa as consultas no banco; sem essa conexão, carrega as sete tabelas de data/normalized/ em um banco SQLite temporário na memória. As consultas dessa aba usam a base de demonstração do projeto, não os filtros de período nem o CSV simples enviado na sessão.

### Dados de outra pizzaria

Para uma pizzaria com poucos dados estruturados, escolha **Enviar CSV único da pizzaria**. As colunas obrigatórias são data e quantidade; pedido, horário, produto, preço, categoria, tamanho e ingredientes são opcionais e habilitam apenas as análises correspondentes.

A previsão requer pelo menos 56 dias consecutivos. Inclua todos os dias do período e use quantidade zero quando não houver venda ou a pizzaria estiver fechada. Se a conexão SQL Server local falhar por falta do driver ODBC no WSL, o painel avisa e usa a base local quando os CSVs normalizados estiverem disponíveis. Para usar SQL Server sem instalar o driver no WSL, execute make all.

Consulte o [Manual do Streamlit](MANUAL_STREAMLIT.md) para saber mais sobre as fontes de dados, consultas e limites das métricas. Consulte o [Manual da regressão linear](MANUAL_REGRESSAO_LINEAR.md) para conhecer os dados exigidos pelo modelo e interpretar a previsão.

No teste feito pelo grupo a partir de um clone limpo, o SQL Server iniciou, a auditoria do ETL foi executada, as sete tabelas foram carregadas e exportadas, e o Streamlit indicou o SQL Server como fonte. A consulta 6.4 também foi executada no SQL Server, com totais reconciliados de 21.350 pedidos e 49.574 pizzas.

## Principais análises

O arquivo 03_analysis_queries.sql contém consultas sobre:

- filtros com BETWEEN, IN e LIKE;
- junções INNER, LEFT, RIGHT e FULL OUTER JOIN;
- subconsultas para identificar pizzas mais caras e calcular participação na receita;
- operações UNION, INTERSECT e EXCEPT para comparar ingredientes entre categorias;
- análise de produtos comprados em conjunto, classificação de receita por categoria, complexidade das receitas e segmentação de pedidos, usando CTEs, junções da tabela consigo mesma, funções de janela e HAVING.

**Observação sobre métricas:** receita bruta não é lucro. A base de demonstração não contém custos dos ingredientes, quantidades usadas por receita, desperdício ou mão de obra. Para calcular rentabilidade ou consumo real, a pizzaria precisa registrar esses dados.
