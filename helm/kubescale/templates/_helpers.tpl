{{/*
Expand the name of the chart.
*/}}
{{- define "kubescale.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "kubescale.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "kubescale.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "kubescale.labels" -}}
helm.sh/chart: {{ include "kubescale.chart" . }}
{{ include "kubescale.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
environment: {{ .Values.environment | quote }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "kubescale.selectorLabels" -}}
app.kubernetes.io/name: {{ include "kubescale.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Gateway component fullname & selector labels
*/}}
{{- define "kubescale.gateway.fullname" -}}
{{- printf "%s-gateway" (include "kubescale.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "kubescale.gateway.selectorLabels" -}}
app.kubernetes.io/name: {{ include "kubescale.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: gateway
{{- end }}

{{/*
Inference component fullname & selector labels
*/}}
{{- define "kubescale.inference.fullname" -}}
{{- printf "%s-inference" (include "kubescale.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "kubescale.inference.selectorLabels" -}}
app.kubernetes.io/name: {{ include "kubescale.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: inference
{{- end }}

{{/*
Worker component fullname & selector labels
*/}}
{{- define "kubescale.worker.fullname" -}}
{{- printf "%s-worker" (include "kubescale.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "kubescale.worker.selectorLabels" -}}
app.kubernetes.io/name: {{ include "kubescale.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: worker
{{- end }}

