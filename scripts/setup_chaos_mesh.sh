#!/usr/bin/env bash
# ==============================================================================
# Install Chaos Mesh Operator for Fault Injection & Resilience Testing
# ==============================================================================

set -euo pipefail

CHAOS_NAMESPACE="chaos-mesh"

echo "======================================================================"
echo "  Installing Chaos Mesh Operator"
echo "  Namespace: ${CHAOS_NAMESPACE}"
echo "======================================================================"

if ! command -v kubectl &> /dev/null; then
    echo "[ERROR] 'kubectl' is not installed or not in PATH."
    exit 1
fi

kubectl create namespace "${CHAOS_NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

if command -v helm &> /dev/null; then
    echo ">>> Adding Chaos Mesh Helm repository..."
    helm repo add chaos-mesh https://charts.chaos-mesh.org
    helm repo update

    echo ">>> Installing Chaos Mesh Helm release..."
    helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \
        --namespace "${CHAOS_NAMESPACE}" \
        --set chaosDaemon.runtime=containerd \
        --set chaosDaemon.socketPath=/run/containerd/containerd.sock \
        --set dashboard.securityMode=false
else
    echo ">>> Installing Chaos Mesh via official installation script..."
    curl -sSL https://mirrors.chaos-mesh.org/v2.6.3/install.sh | bash -s -- --local containerd
fi

echo ">>> Waiting for Chaos Mesh Controller Manager to be ready..."
kubectl rollout status deployment/chaos-controller-manager -n "${CHAOS_NAMESPACE}" --timeout=180s || true

echo ""
echo "======================================================================"
echo "  [SUCCESS] Chaos Mesh Operator Installed Successfully!"
echo "  To access the Chaos Dashboard UI:"
echo "  kubectl port-forward svc/chaos-dashboard 2333:2333 -n ${CHAOS_NAMESPACE}"
echo "  URL: http://localhost:2333"
echo "======================================================================"
