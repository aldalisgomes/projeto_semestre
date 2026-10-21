.PHONY: help setup db-up db-down run clean

# Variables
DOCKER_COMPOSE_FILE = docker/docker-compose.yml
PROJECT_NAME = vesuvio
IMAGE_NAME = vesuvio-pipeline

help: ## Show this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

setup: ## Install Python dependencies locally (for development)
	pip install -r requirements.txt

db-up: ## Start the SQL Server database with Docker in the background
	docker-compose -p $(PROJECT_NAME) -f $(DOCKER_COMPOSE_FILE) up -d
	@echo "Waiting for SQL Server to start... (Please wait about 15 seconds before running the pipeline)"

db-down: ## Stop and remove the database containers and networks
	docker-compose -p $(PROJECT_NAME) -f $(DOCKER_COMPOSE_FILE) down

run: ## Build the Docker image and run the complete ETL pipeline
	docker build -t $(IMAGE_NAME) .
	docker run --rm --network $(PROJECT_NAME)_default $(IMAGE_NAME)

clean: ## Clean up temporary Python cache files
	find . -type d -name "__pycache__" -exec rm -rf {} +