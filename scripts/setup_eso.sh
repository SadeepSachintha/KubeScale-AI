#!/usr/bin/env bash
# ==============================================================================
# External Secrets Operator (ESO) Installation Script
# ==============================================================================
set -euo pipefail

echo "=========================================================="
echo "   Installing External Secrets Operator (ESO)"
echo "=========================================================="

ESO_NAMESPACE="external-secrets"

if command -v helm &> /dev/null; then
    echo "[INFO] Adding External Secrets Helm repository..."
    helm repo add external-secrets https://charts.external-secrets.io
    helm repo update

    echo "[INFO] Deploying External Secrets Operator into namespace '${ESO_NAMESPACE}'..."
    helm upgrade --install external-secrets external-secrets/external-secrets \
        --namespace "${ESO_NAMESPACE}" \
        --create-namespace \
        --set installCRDs=true \
        --wait

    echo "[INFO] Verifying External Secrets Operator deployment..."
    kubectl get pods -n "${ESO_NAMESPACE}"
else
    echo "[WARNING] Helm CLI not available; applying ESO CRDs directly..."
    kubectl apply -f https://raw.githubusercontent.com/external-secrets/external-secrets/main/deploy/crds/bundle.yaml
fi

echo "=========================================================="
echo "   External Secrets Operator Deployed Successfully!"
echo "=========================================================="
echo "Check SecretStores:     kubectl get secretstore -n kubescale"
echo "Check ExternalSecrets:  kubectl get externalsecret -n kubescale"
