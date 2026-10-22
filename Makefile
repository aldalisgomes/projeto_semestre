.PHONY: help setup db-up db-down run normalize dashboard dashboard-docker all clean
.NOTPARALLEL: all

# Fluxo completo: Windows + WSL2 Ubuntu + integração com Docker Desktop ou Linux nativo x86-64.
# O grupo validou o fluxo no Windows, WSL2 Ubuntu, Docker Desktop e VS Code.
# Linux nativo requer GNU Make, Bash, Docker Engine e o complemento Docker Compose v2; VS Code é opcional.
# make all executa o ETL de demonstração, que apaga e recria PizzaSales. Não use em produção.
DOCKER_COMPOSE_FILE = docker/docker-compose.yml
DOCKER_COMPOSE ?= docker compose
PROJECT_NAME = vesuvio
IMAGE_NAME = vesuvio-pipeline
PYTHON ?= python3
VENV_PYTHON = .venv/bin/python
STREAMLIT_PORT ?= 8501
# Os caracteres da senha reservados em URLs estão codificados; as credenciais correspondem a docker-compose.yml.
PIZZA_DATABASE_URL ?= mssql+pyodbc://sa:SenhaForte%402026%21@localhost:1433/PizzaSales?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes
# Enviar uma solicitação de saúde válida ao Streamlit e abrir o navegador sem registrar erros da verificação.
OPEN_BROWSER = nohup bash -c 'open_browser() { if command -v explorer.exe >/dev/null 2>&1 && explorer.exe "http://localhost:$(STREAMLIT_PORT)" >/dev/null 2>&1; then return 0; fi; if command -v xdg-open >/dev/null 2>&1 && { [ -n "$$DISPLAY" ] || [ -n "$$WAYLAND_DISPLAY" ]; }; then xdg-open "http://localhost:$(STREAMLIT_PORT)" >/dev/null 2>&1; fi; }; health_ok() { ( exec 3<>/dev/tcp/127.0.0.1/$(STREAMLIT_PORT) || exit 1; printf "GET /_stcore/health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n" >&3; IFS= read -r -t 2 status <&3 || exit 1; [[ "$$status" == *" 200 "* ]] ) 2>/dev/null; }; for attempt in {1..60}; do if health_ok; then open_browser; exit 0; fi; sleep 1; done' >/dev/null 2>&1 </dev/null &

help: ## Exibe os comandos disponíveis
	@echo "Uso: make [alvo]"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*## .*$$' $(MAKEFILE_LIST) | awk -F '## ' '{split($$1, target, ":"); printf "  %-18s %s\n", target[1], $$2}'

setup: ## Cria o ambiente virtual local e instala as dependências do projeto
	$(PYTHON) -m venv .venv
	$(VENV_PYTHON) -m pip install -r requirements.txt

db-up: ## Inicia o SQL Server e aguarda a aceitação de conexões
	$(DOCKER_COMPOSE) -p $(PROJECT_NAME) -f $(DOCKER_COMPOSE_FILE) up -d
	@echo "Aguardando o SQL Server ficar pronto..."
	@attempt=0; \
	until docker logs vesuvio_sql_server 2>&1 | grep -q "SQL Server is now ready for client connections"; do \
		attempt=$$((attempt + 1)); \
		if [ $$attempt -ge 60 ]; then \
			echo "O SQL Server não ficou pronto em até 120 segundos." >&2; \
			docker logs vesuvio_sql_server; \
			exit 1; \
		fi; \
		sleep 2; \
	done
	@echo "SQL Server está pronto em localhost:1433."

db-down: ## Para/remove o contêiner e a rede do SQL Server; preserva o volume de dados
	$(DOCKER_COMPOSE) -p $(PROJECT_NAME) -f $(DOCKER_COMPOSE_FILE) down

run: db-up ## Constrói a imagem do ETL e carrega o banco SQL Server
	docker build -t $(IMAGE_NAME) .
	docker run --rm --network $(PROJECT_NAME)_default $(IMAGE_NAME)

normalize: setup ## Gera ou atualiza os sete CSVs normalizados
	$(VENV_PYTHON) src/04_exportar_base_normalizada.py

dashboard: normalize ## Atualiza os CSVs e inicia o Streamlit local (requer Python; SQL Server também requer ODBC local)
	@$(OPEN_BROWSER)
	PIZZA_DATABASE_URL='$(PIZZA_DATABASE_URL)' $(VENV_PYTHON) -m streamlit run src/03_streamlit_dashboard.py --server.address 127.0.0.1 --server.port $(STREAMLIT_PORT) --server.headless true

dashboard-docker: db-up ## Exporta os CSVs e inicia o Streamlit no Docker (não requer Python nem ODBC local)
	docker build -t $(IMAGE_NAME) .
	@mkdir -p data/normalized
	docker run --rm -v "$(CURDIR)/data:/app/data" $(IMAGE_NAME) python src/04_exportar_base_normalizada.py
	@$(OPEN_BROWSER)
	docker run --rm --network $(PROJECT_NAME)_default -p $(STREAMLIT_PORT):8501 -e PIZZA_DATABASE_URL='mssql+pyodbc://sa:SenhaForte%402026%21@pizza_sql_server:1433/PizzaSales?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes' $(IMAGE_NAME) streamlit run src/03_streamlit_dashboard.py --server.address 0.0.0.0 --server.port 8501 --server.headless true

all: db-up run dashboard-docker ## Demonstração completa: SQL Server, ETL, tabelas normalizadas e painel Docker
	@:

clean: ## Remove arquivos temporários de cache do Python
	find . -type d -name "__pycache__" -exec rm -rf {} +
