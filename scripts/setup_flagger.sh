#!/usr/bin/env bash
# ==============================================================================
# Flagger Progressive Delivery Controller Installation Script
# ==============================================================================
set -euo pipefail

echo "=========================================================="
echo "   Installing Flagger for Automated Canary Rollouts"
echo "=========================================================="

FLAGGER_NAMESPACE="ingress-nginx"
PROMETHEUS_ENDPOINT="http://prometheus-stack-kube-prom-prometheus.monitoring.svc:9090"

if command -v helm &> /dev/null; then
    echo "[INFO] Adding Flagger Helm repository..."
    helm repo add flagger https://flagger.app
    helm repo update

    echo "[INFO] Deploying Flagger Controller for NGINX Ingress..."
    helm upgrade --install flagger flagger/flagger \
        --namespace "${FLAGGER_NAMESPACE}" \
        --create-namespace \
        --set crd.create=true \
        --set meshProvider=nginx \
        --set metricsServer="${PROMETHEUS_ENDPOINT}" \
        --wait

    echo "[INFO] Verifying Flagger deployment..."
    kubectl get pods -n "${FLAGGER_NAMESPACE}" -l app.kubernetes.io/name=flagger
else
    echo "[WARNING] Helm CLI not available; applying Flagger standard manifests..."
    kubectl apply -k https://github.com/fluxcd/flagger//kustomize/kubernetes
fi

echo "=========================================================="
echo "   Flagger Controller Deployed Successfully!"
echo "=========================================================="
echo "Check Canary status with:  kubectl get canaries -n kubescale"
echo "Describe Canary events:    kubectl describe canary kubescale-gateway -n kubescale"
