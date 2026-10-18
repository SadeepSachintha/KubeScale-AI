#!/usr/bin/env bash
# ==============================================================================
# Kyverno Policy Engine Installation & Policy Enforcement Script
# ==============================================================================
set -euo pipefail

echo "=========================================================="
echo "   Installing Kyverno Cloud-Native Policy Controller"
echo "=========================================================="

KYVERNO_NAMESPACE="kyverno"

if command -v helm &> /dev/null; then
    echo "[INFO] Adding Kyverno Helm repository..."
    helm repo add kyverno https://kyverno.github.io/kyverno
    helm repo update

    echo "[INFO] Deploying Kyverno Controller into namespace '${KYVERNO_NAMESPACE}'..."
    helm upgrade --install kyverno kyverno/kyverno \
        --namespace "${KYVERNO_NAMESPACE}" \
        --create-namespace \
        --wait

    echo "[INFO] Verifying Kyverno deployment..."
    kubectl get pods -n "${KYVERNO_NAMESPACE}"
else
    echo "[WARNING] Helm CLI not available; applying Kyverno standard release YAML..."
    kubectl apply -f https://github.com/kyverno/kyverno/releases/download/v1.12.0/install.yaml
fi

echo "[INFO] Applying Zero-Trust Security Policies..."
kubectl apply -f security/kyverno/

echo "=========================================================="
echo "   Kyverno Policies Enforced Successfully!"
echo "=========================================================="
echo "Check ClusterPolicies:  kubectl get clusterpolicy"
echo "Check PolicyReports:    kubectl get policyreport -A"
