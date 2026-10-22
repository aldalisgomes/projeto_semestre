.PHONY: help setup db-up db-down run normalize dashboard dashboard-docker all clean
.NOTPARALLEL: all

# Run these targets from WSL/Linux with GNU Make and Docker Compose v2.
DOCKER_COMPOSE_FILE = docker/docker-compose.yml
DOCKER_COMPOSE ?= docker compose
PROJECT_NAME = vesuvio
IMAGE_NAME = vesuvio-pipeline
PYTHON ?= python3
VENV_PYTHON = .venv/bin/python
STREAMLIT_PORT ?= 8501
# Password characters reserved by URLs are percent-encoded; credentials match docker-compose.yml.
PIZZA_DATABASE_URL ?= mssql+pyodbc://sa:SenhaForte%402026%21@localhost:1433/PizzaSales?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes

help: ## Show available commands
	@echo "Usage: make [target]"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*## .*$$' $(MAKEFILE_LIST) | awk -F '## ' '{split($$1, target, ":"); printf "  %-18s %s\n", target[1], $$2}'

setup: ## Create the local virtual environment and install project dependencies
	$(PYTHON) -m venv .venv
	$(VENV_PYTHON) -m pip install -r requirements.txt

db-up: ## Start SQL Server and wait until it accepts connections
	$(DOCKER_COMPOSE) -p $(PROJECT_NAME) -f $(DOCKER_COMPOSE_FILE) up -d
	@echo "Waiting for SQL Server readiness..."
	@attempt=0; \
	until docker logs vesuvio_sql_server 2>&1 | grep -q "SQL Server is now ready for client connections"; do \
		attempt=$$((attempt + 1)); \
		if [ $$attempt -ge 60 ]; then \
			echo "SQL Server did not become ready within 120 seconds." >&2; \
			docker logs vesuvio_sql_server; \
			exit 1; \
		fi; \
		sleep 2; \
	done
	@echo "SQL Server is ready on localhost:1433."

db-down: ## Stop and remove the SQL Server container and network
	$(DOCKER_COMPOSE) -p $(PROJECT_NAME) -f $(DOCKER_COMPOSE_FILE) down

run: db-up ## Build the ETL image and load the SQL Server database
	docker build -t $(IMAGE_NAME) .
	docker run --rm --network $(PROJECT_NAME)_default $(IMAGE_NAME)

normalize: setup ## Generate/refresh the seven normalized CSV tables
	$(VENV_PYTHON) src/04_exportar_base_normalizada.py

dashboard: normalize ## Refresh normalized CSVs and run Streamlit locally on port 8501
	PIZZA_DATABASE_URL='$(PIZZA_DATABASE_URL)' $(VENV_PYTHON) -m streamlit run src/03_streamlit_dashboard.py --server.address 0.0.0.0 --server.port $(STREAMLIT_PORT)

dashboard-docker: db-up ## Export normalized CSVs and run Streamlit in Docker on port 8501
	docker build -t $(IMAGE_NAME) .
	@mkdir -p data/normalized
	docker run --rm -v "$(CURDIR)/data:/app/data" $(IMAGE_NAME) python src/04_exportar_base_normalizada.py
	docker run --rm --network $(PROJECT_NAME)_default -p $(STREAMLIT_PORT):8501 -e PIZZA_DATABASE_URL='mssql+pyodbc://sa:SenhaForte%402026%21@pizza_sql_server:1433/PizzaSales?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes' $(IMAGE_NAME) streamlit run src/03_streamlit_dashboard.py --server.address 0.0.0.0 --server.port 8501

all: db-up run dashboard-docker ## Start SQL Server, run ETL, export normalized tables and launch Docker dashboard
	@:

clean: ## Remove temporary Python cache files
	find . -type d -name "__pycache__" -exec rm -rf {} +
