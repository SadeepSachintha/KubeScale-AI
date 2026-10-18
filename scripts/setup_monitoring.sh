#!/usr/bin/env bash
# ==============================================================================
# Prometheus Operator & Grafana Stack Installation Script
# ==============================================================================
set -euo pipefail

echo "=========================================================="
echo "   Installing Prometheus Stack & Curated Grafana Dashboards"
echo "=========================================================="

MONITORING_NAMESPACE="monitoring"
KUBESCALE_NAMESPACE="kubescale"

if command -v helm &> /dev/null; then
    echo "[INFO] Adding Prometheus Community Helm repository..."
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
    helm repo update

    echo "[INFO] Deploying kube-prometheus-stack into namespace '${MONITORING_NAMESPACE}'..."
    helm upgrade --install prometheus-stack prometheus-community/kube-prometheus-stack \
        --namespace "${MONITORING_NAMESPACE}" \
        --create-namespace \
        --set grafana.sidecar.dashboards.enabled=true \
        --set grafana.sidecar.dashboards.label=grafana_dashboard \
        --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
        --set prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues=false \
        --set prometheus.prometheusSpec.ruleSelectorNilUsesHelmValues=false \
        --wait
else
    echo "[WARNING] Helm CLI not found. Applying Prometheus Operator CRDs directly..."
    kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/example/prometheus-operator-crd/monitoring.coreos.com_servicemonitors.yaml
    kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/main/example/prometheus-operator-crd/monitoring.coreos.com_prometheusrules.yaml
fi

echo "[INFO] Importing KubeScale AI Curated Dashboards into Grafana..."
kubectl create configmap kubescale-overview-dashboard \
    --from-file=monitoring/dashboards/kubescale-overview.json \
    -n "${MONITORING_NAMESPACE}" \
    --dry-run=client -o yaml | kubectl apply -f -
kubectl label configmap kubescale-overview-dashboard grafana_dashboard="1" -n "${MONITORING_NAMESPACE}" --overwrite

kubectl create configmap kubescale-triton-dashboard \
    --from-file=monitoring/dashboards/triton-inference.json \
    -n "${MONITORING_NAMESPACE}" \
    --dry-run=client -o yaml | kubectl apply -f -
kubectl label configmap kubescale-triton-dashboard grafana_dashboard="1" -n "${MONITORING_NAMESPACE}" --overwrite

kubectl create configmap kubescale-kafka-dashboard \
    --from-file=monitoring/dashboards/kafka-streaming.json \
    -n "${MONITORING_NAMESPACE}" \
    --dry-run=client -o yaml | kubectl apply -f -
kubectl label configmap kubescale-kafka-dashboard grafana_dashboard="1" -n "${MONITORING_NAMESPACE}" --overwrite

echo "=========================================================="
echo "   Monitoring Stack & Dashboards Deployed Successfully!"
echo "=========================================================="
echo "Access Grafana:   kubectl port-forward svc/prometheus-stack-grafana 3000:80 -n ${MONITORING_NAMESPACE}"
echo "URL:              http://localhost:3000 (User: admin / Password: prom-operator)"
echo "Access Prometheus: kubectl port-forward svc/prometheus-stack-kube-prom-prometheus 9090:9090 -n ${MONITORING_NAMESPACE}"
