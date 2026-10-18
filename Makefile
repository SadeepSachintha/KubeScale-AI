# ==============================================================================
# KubeScale AI Automation Makefile
# ==============================================================================

SHELL := /bin/bash
PROJECT_NAME := kubescale-ai
NAMESPACE := kubescale
DOCKER_IMAGE := kubescale/gateway:latest

.PHONY: help init test lint docker-build worker-build helm-lint helm-template tf-fmt tf-validate tf-plan cluster-local load-test clean

help: ## Show this help message
	@echo "======================================================================"
	@echo "                    KubeScale AI CLI & Automation"
	@echo "======================================================================"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

init: ## Initialize local Python virtual environment and dependencies
	@echo "--> Initializing Python virtual environment..."
	python3 -m venv .venv
	source .venv/bin/activate && pip install --upgrade pip && \
		pip install -r gateway/requirements.txt && pip install -r worker/requirements.txt
	@echo "--> Initialized successfully. Activate with: source .venv/bin/activate"

test: ## Run unit and integration tests across gateway and worker services
	@echo "--> Running pytest test suite..."
	source .venv/bin/activate && pytest -v

docker-build: ## Build FastAPI Gateway Docker container image
	@echo "--> Building Gateway Docker image $(DOCKER_IMAGE)..."
	docker build -t $(DOCKER_IMAGE) ./gateway

worker-build: ## Build Async Inference Worker Docker container image
	@echo "--> Building Worker Docker image kubescale/worker:latest..."
	docker build -t kubescale/worker:latest ./worker


helm-lint: ## Lint Helm chart using local Helm or fallback container
	@echo "--> Linting Helm chart..."
	@if command -v helm &> /dev/null; then \
		helm lint ./helm/kubescale && helm lint ./helm/kubescale -f ./helm/kubescale/values-prod.yaml; \
	else \
		docker run --rm -v "$$(pwd):/apps" alpine/helm:latest lint /apps/helm/kubescale; \
	fi

helm-template: ## Render Helm chart templates to stdout for verification
	@echo "--> Rendering Helm templates..."
	@if command -v helm &> /dev/null; then \
		helm template kubescale ./helm/kubescale; \
	else \
		docker run --rm -v "$$(pwd):/apps" alpine/helm:latest template kubescale /apps/helm/kubescale; \
	fi

tf-fmt: ## Format Terraform configuration files
	@echo "--> Checking/formatting Terraform files..."
	@if command -v terraform &> /dev/null; then \
		terraform -chdir=terraform fmt; \
	else \
		docker run --rm -v "$$(pwd)/terraform:/workspace" -w /workspace hashicorp/terraform:latest fmt; \
	fi

tf-validate: ## Initialize and validate Terraform configuration
	@echo "--> Validating Terraform configuration..."
	@if command -v terraform &> /dev/null; then \
		terraform -chdir=terraform init -backend=false && terraform -chdir=terraform validate; \
	else \
		docker run --rm -v "$$(pwd)/terraform:/workspace" -w /workspace hashicorp/terraform:latest init -backend=false && \
		docker run --rm -v "$$(pwd)/terraform:/workspace" -w /workspace hashicorp/terraform:latest validate; \
	fi

tf-plan: ## Run Terraform plan using sample variables
	@echo "--> Running Terraform plan..."
	@if command -v terraform &> /dev/null; then \
		terraform -chdir=terraform plan -var-file=terraform.tfvars.example; \
	else \
		docker run --rm -v "$$(pwd)/terraform:/workspace" -w /workspace hashicorp/terraform:latest plan -var-file=terraform.tfvars.example; \
	fi

cluster-local: ## Bootstrap local Kubernetes cluster with Strimzi and Helm stack
	@echo "--> Bootstrapping local Kubernetes cluster..."
	./scripts/setup_local_cluster.sh

keda-install: ## Install KEDA Operator for Kafka lag and Triton queue autoscaling
	@echo "--> Installing KEDA Operator..."
	./scripts/setup_keda.sh


load-test: ## Run concurrent load testing script against local gateway
	@echo "--> Launching concurrent load generator..."
	python3 ./scripts/load_test.py --url http://localhost:8000/v1/models/sentiment_onnx/predict --requests 500 --concurrency 25

clean: ## Clean build artifacts, pycache, and temporary files
	@echo "--> Cleaning workspace..."
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .coverage htmlcov/
	@echo "Workspace cleaned."
