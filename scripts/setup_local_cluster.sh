#!/usr/bin/env bash
# ==============================================================================
# Local Hybrid Cluster Bootstrap Script (Kind / Minikube / K3s)
# ==============================================================================
set -euo pipefail

echo "=========================================================="
echo "   KubeScale AI: Local Kubernetes Cluster Setup"
echo "=========================================================="

CLUSTER_NAME="kubescale-local"
NAMESPACE="kubescale"

# Check if kind is installed
if command -v kind &> /dev/null; then
    echo "[INFO] Using Kind for local cluster..."
    if ! kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
        echo "[INFO] Creating Kind cluster '${CLUSTER_NAME}'..."
        cat <<EOF | kind create cluster --name "${CLUSTER_NAME}" --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        node-labels: "ingress-ready=true"
  extraPortMappings:
  - containerPort: 80
    hostPort: 80
    protocol: TCP
  - containerPort: 443
    hostPort: 443
    protocol: TCP
- role: worker
- role: worker
EOF
    else
        echo "[INFO] Kind cluster '${CLUSTER_NAME}' already exists."
    fi
elif command -v minikube &> /dev/null; then
    echo "[INFO] Using Minikube for local cluster..."
    minikube start --nodes 3 --cpus 4 --memory 8192
    minikube addons enable ingress
    minikube addons enable metrics-server
else
    echo "[WARNING] Neither kind nor minikube found in PATH."
    echo "[INFO] Assuming existing Kubernetes context from kubectl:"
    kubectl cluster-info || true
fi

echo "[INFO] Creating namespace '${NAMESPACE}'..."
kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

echo "[INFO] Installing Strimzi Kafka Operator..."
kubectl apply -f 'https://strimzi.io/install/latest?namespace='"${NAMESPACE}" -n "${NAMESPACE}" || true

echo "[INFO] Building Gateway container image locally..."
docker build -t kubescale/gateway:latest ./gateway

if command -v kind &> /dev/null && kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
    echo "[INFO] Loading gateway image into Kind cluster nodes..."
    kind load docker-image kubescale/gateway:latest --name "${CLUSTER_NAME}"
fi

echo "[INFO] Applying Helm chart..."
if command -v helm &> /dev/null; then
    helm upgrade --install kubescale ./helm/kubescale -n "${NAMESPACE}"
else
    echo "[INFO] Helm CLI not found; running template deployment via kubectl..."
    docker run --rm -v "$(pwd):/apps" alpine/helm:latest template kubescale /apps/helm/kubescale | kubectl apply -n "${NAMESPACE}" -f -
fi

echo "=========================================================="
echo "   KubeScale AI Cluster Provisioned Successfully!"
echo "=========================================================="
echo "Check pods with:   kubectl get pods -n ${NAMESPACE}"
echo "Check HPA with:    kubectl get hpa -n ${NAMESPACE}"
echo "Port forward API:  kubectl port-forward svc/kubescale-gateway 8000:8000 -n ${NAMESPACE}"
