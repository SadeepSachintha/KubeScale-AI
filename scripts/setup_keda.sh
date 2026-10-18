#!/usr/bin/env bash
# ==============================================================================
# KEDA (Kubernetes Event-driven Autoscaling) Installation Script
# ==============================================================================
set -euo pipefail

echo "=========================================================="
echo "   Installing KEDA Operator for Event-Driven Autoscaling"
echo "=========================================================="

KEDA_NAMESPACE="keda"

if command -v helm &> /dev/null; then
    echo "[INFO] Adding KEDA Helm repository..."
    helm repo add kedacore https://kedacore.github.io/charts
    helm repo update

    echo "[INFO] Deploying KEDA Operator into namespace '${KEDA_NAMESPACE}'..."
    helm upgrade --install keda kedacore/keda \
        --namespace "${KEDA_NAMESPACE}" \
        --create-namespace \
        --set priorityClassName="" \
        --wait

    echo "[INFO] Verifying KEDA deployments..."
    kubectl get pods -n "${KEDA_NAMESPACE}"
else
    echo "[INFO] Helm CLI not available; applying KEDA standard YAML manifest..."
    kubectl apply --server-side -f https://github.com/kedacore/keda/releases/download/v2.14.0/keda-2.14.0.yaml
fi

echo "=========================================================="
echo "   KEDA Operator Installed Successfully!"
echo "=========================================================="
echo "Verify ScaledObjects with:  kubectl get scaledobject -n kubescale"
echo "Verify HPA generated:       kubectl get hpa -n kubescale"
