#!/usr/bin/env bash
# ==============================================================================
# ArgoCD GitOps Controller Installation & Bootstrap Script
# ==============================================================================
set -euo pipefail

echo "=========================================================="
echo "   Installing ArgoCD GitOps Engine & Root Application"
echo "=========================================================="

ARGOCD_NAMESPACE="argocd"

echo "[INFO] Creating namespace '${ARGOCD_NAMESPACE}'..."
kubectl create namespace "${ARGOCD_NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

echo "[INFO] Applying ArgoCD core manifests..."
kubectl apply -n "${ARGOCD_NAMESPACE}" -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

echo "[INFO] Waiting for ArgoCD Server to become ready..."
kubectl rollout status deployment/argocd-server -n "${ARGOCD_NAMESPACE}" --timeout=180s || true

echo "[INFO] Applying KubeScale AI Root GitOps Application (App-of-Apps)..."
kubectl apply -f gitops/root-application.yaml

echo "=========================================================="
echo "   ArgoCD Deployed & Root GitOps App Bootstrapped!"
echo "=========================================================="
echo "Port forward UI: kubectl port-forward svc/argocd-server -n ${ARGOCD_NAMESPACE} 8080:443"
echo "Web UI URL:      https://localhost:8080 (Username: admin)"
echo ""
echo "To fetch initial admin password:"
echo "kubectl -n ${ARGOCD_NAMESPACE} get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d && echo"
