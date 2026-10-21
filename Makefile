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

gateway-go-test: ## Run unit tests for Go High-Throughput Gateway
	@echo "--> Running Go gateway test suite..."
	cd gateway-go && go test -v ./...

docker-build: ## Build FastAPI Gateway Docker container image
	@echo "--> Building Gateway Docker image $(DOCKER_IMAGE)..."
	docker build -t $(DOCKER_IMAGE) ./gateway

gateway-go-docker: ## Build Go High-Throughput Gateway Docker container image (<25MB)
	@echo "--> Building Go Gateway Docker image kubescale/gateway-go:latest..."
	docker build -t kubescale/gateway-go:latest ./gateway-go

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

monitoring-install: ## Deploy Prometheus Operator, Alertmanager, and Curated Grafana Dashboards
	@echo "--> Deploying Prometheus & Grafana stack..."
	./scripts/setup_monitoring.sh

eso-install: ## Install External Secrets Operator (ESO) for AWS Secrets Manager / Vault sync
	@echo "--> Installing External Secrets Operator..."
	./scripts/setup_eso.sh

flagger-install: ## Install Flagger Progressive Delivery Controller for Canary Deployments
	@echo "--> Installing Flagger Controller..."
	./scripts/setup_flagger.sh

argocd-install: ## Install ArgoCD GitOps engine and apply App-of-Apps root application
	@echo "--> Installing ArgoCD and applying GitOps root application..."
	./scripts/setup_argocd.sh

kyverno-install: ## Install Kyverno policy engine and enforce Zero-Trust admission rules
	@echo "--> Installing Kyverno and applying cluster security policies..."
	./scripts/setup_kyverno.sh

tracing-install: ## Deploy OpenTelemetry & Jaeger Distributed Tracing stack
	@echo "--> Deploying OpenTelemetry Collector & Jaeger APM stack..."
	./scripts/setup_tracing.sh

models-generate: ## Generate dummy ONNX model artifacts for Triton repository
	@echo "--> Generating ONNX model artifacts..."
	source .venv/bin/activate && python models/scripts/generate_dummy_model.py

model-control-demo: ## Run live demonstration of Triton Model Control API and hot reload
	@echo "--> Running Triton Live Reload & Multi-Model Serving demonstration..."
	./scripts/demo_model_control.sh

tracing-demo: ## Run live demonstration of distributed tracing with W3C context propagation
	@echo "--> Running OpenTelemetry distributed tracing demonstration..."
	./scripts/demo_tracing.sh

chaos-install: ## Install Chaos Mesh Operator for fault injection and resilience testing
	@echo "--> Installing Chaos Mesh Operator..."
	./scripts/setup_chaos_mesh.sh

chaos-run: ## Execute automated Chaos Mesh fault-injection experiments and verify self-healing
	@echo "--> Running Chaos Mesh resilience experiments..."
	./scripts/run_chaos_experiments.sh

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
