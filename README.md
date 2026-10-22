# Pizza Place Sales - Data Engineering & Analytics Pipeline

[![Python](https://img.shields.io/badge/Python-3.10-blue.svg)](https://www.python.org/)
[![SQL Server](https://img.shields.io/badge/SQL_Server-2022-red.svg)](https://www.microsoft.com/en-us/sql-server)
[![Docker](https://img.shields.io/badge/Docker-Enabled-blue.svg)](https://www.docker.com/)

**Repository:** [https://github.com/aldalisgomes/projeto_semestre](https://github.com/aldalisgomes/projeto_semestre)

## Project Overview
This case study covers a complete end-to-end data pipeline for a fictional **Pizza Place**, going from extracting denormalized CSV data to supporting advanced business decision-making.

The core objective was to restructure a relational database that suffered from redundancy and update anomalies. This was achieved by:
1. Applying **Normal Forms (1NF and 3NF)** to clean the data.
2. Automating the ETL data load into **SQL Server** using **Python** (Pandas, SQLAlchemy).
3. Extracting business intelligence using advanced **T-SQL**.

## Technologies & Tools
* **Languages:** Python (Pandas, SQLAlchemy, PyODBC), T-SQL
* **Database:** Microsoft SQL Server (Containerized)
* **Infrastructure:** Docker & Docker Compose
* **Automation:** Makefile
* **Modeling:** Peter Chen and Crow's Foot notations

## Project Structure
```text
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
├── README.md
└── requirements.txt
```

## Database Architecture & Data Modeling

### Normalization Process

* **First Normal Form (1NF):** The original source data contained an ingredients column with multiple comma-separated values. These were decomposed into an atomic structure, creating the associative table pizza_type_ingredients.
* **Third Normal Form (3NF):** Pizza categories were originally stored as redundant text. They were normalized into a separate dimension table (categories) with unique numeric identifiers.

### Data Quality & Business Rules (via Python)

* Default addition of Mozzarella Cheese to all pizzas to standardize recipes.
* Default addition of Tomato Sauce for pizzas without a specified sauce.

### Entity Relationship Diagram (ERD)

```text
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
```

## How to Run This Project Locally

### 1. Prerequisites
* Docker Desktop installed and running.
* Make installed (optional, but recommended for ease of use).
* Azure Data Studio (or SQL Server Management Studio) for database validation.

### 2. Clone the Repository
Open your Linux terminal (or WSL/Git Bash on Windows) and run:
```bash
git clone https://github.com/aldalisgomes/projeto_semestre
cd projeto_semestre
```

### 3. Start the Infrastructure (SQL Server)
Use the provided Makefile to quickly spin up the database container:
```bash
make db-up
```
Note: Docker Compose creates the `vesuvio_default` network and starts SQL Server on port 1433. The Makefile waits for the server readiness message before returning.

### 4. Run the ETL Pipeline
Build the Python application container and run the complete ETL pipeline. This step builds the image, connects to the Docker network, audits data, applies normalization rules, and loads the SQL Server database:
```bash
make run
```
You can follow the terminal output to see the detailed data audit (checking nulls and duplicates) and the successful loading of all tables.

### 5. Validation and Analysis
Once the pipeline finishes successfully, you can validate the data and test the business queries. You can do this using either Azure Data Studio or directly in VS Code.

**Option A: Using Azure Data Studio (or SSMS)**
* Open Azure Data Studio (or your preferred SQL client).
* Connect to the database using the following credentials:
  * Server: localhost,1433
  * User: sa
  * Password: SenhaForte@2026!
* Open the 03_analysis_queries.sql file and execute the queries to evaluate advanced JOINs, Subqueries, and Set Operations applied to the pizzeria's business rules.

**Option B: Using VS Code (For Windows / WSL Users)**
If you are using Windows with WSL and started the database using the Makefile infrastructure, here is exactly how to test the queries without leaving your editor:
* **Open the project in VS Code via WSL:** In your WSL terminal, ensure you are inside the cloned project folder, and type exactly:
```bash
code .
```
(Note: This exact command tells your terminal to open VS Code already connected to the WSL Linux environment where your files are located).
* **Install the Extension:** Ensure you have the official SQL Server (mssql) extension by Microsoft installed in your VS Code.
* **Create the Connection:**
  * Press Ctrl+Shift+P (or F1) to open the Command Palette.
  * Type and select: MS SQL: Add Connection.
  * Fill in the exact credentials as prompted step-by-step:
    * Server name: localhost,1433
    * Database name: PizzaSales
    * Authentication Type: SQL Login
    * User name: sa
    * Password: SenhaForte@2026!
    * Trust server certificate: Yes
    * Profile Name: Choose a friendly name (e.g., Pizza Local).
* **Execute the Queries:** Open the 03_analysis_queries.sql file, highlight the specific block of the query you want to test, and press Ctrl+Shift+E (or right-click and select "Execute Query"). The results will appear instantly in a side panel.

### 6. Tear Down & Clean Up
Once finished, you can safely shut down the containers, remove the network, and clean up temporary Python cache files:
```bash
make db-down
make clean
```
Tip: You can run make help at any time to see all available commands, including make setup for installing dependencies locally.

### 7. Streamlit, consultas SQL e fluxo completo pelo Makefile

Na raiz do projeto, em WSL/Ubuntu com GNU Make e Docker Desktop integrados, use:

```bash
make help                 # lista os comandos
make setup                # cria .venv e instala requirements.txt
make normalize            # exporta/atualiza as sete tabelas em data/normalized/
make dashboard            # normaliza e abre o Streamlit local na porta 8501
make dashboard-docker     # normaliza e abre o Streamlit dentro do Docker
make all                  # banco + ETL + CSVs normalizados + painel Docker
```

`make dashboard` configura `PIZZA_DATABASE_URL` para tentar o SQL Server local. Se o banco não estiver disponível, os gráficos e a aba **Consultas SQL** continuam usando as tabelas normalizadas locais. `make dashboard-docker` gera os CSVs normalizados dentro do container e publica o painel em `http://localhost:8501`, sem exigir Python/ODBC instalados no WSL; para que a opção SQL Server dentro do painel tenha dados, execute antes `make run` ou use `make all`.

**Atenção:** o ETL existente executa o DDL de referência, que recria o banco `PizzaSales`. Portanto, `make run` e `make all` devem ser usados em ambiente de demonstração/teste, após proteger qualquer dado que precise ser mantido. Eles não são necessários para abrir o painel com a base normalizada local.

Na nova aba **Consultas SQL**, o painel lê os blocos numerados do `03_analysis_queries.sql`, exibe o código selecionado e mostra a tabela de resultado. Com as tabelas do projeto disponíveis, executa no SQL Server; sem SQL Server, carrega as sete tabelas de `data/normalized/` em SQLite em memória. As consultas não usam os filtros de data da barra lateral.

Consulte [MANUAL_STREAMLIT.md](MANUAL_STREAMLIT.md) para detalhes sobre as fontes de dados, as consultas e os limites das métricas.

## Analytics Highlights
The project includes an SQL script (03_analysis_queries.sql) containing:
* **Complex Filtering:** Usage of BETWEEN, IN, LIKE, and exclusions to segment sales periods and pizza types.
* **Joins:** INNER, LEFT, RIGHT, and FULL OUTER joins to combine normalized tables and identify data orphans.
* **Subqueries:** Identifying top-priced items and calculating revenue percentage contributions by category.
* **Set Operations:** UNION, INTERSECT, and EXCEPT to cross-reference ingredient usage across pizza categories.
* **Advanced Analytics:** Market-basket pairs, revenue ranking by category, recipe-complexity filtering, and order segmentation using CTEs, self joins, window functions, and HAVING.
