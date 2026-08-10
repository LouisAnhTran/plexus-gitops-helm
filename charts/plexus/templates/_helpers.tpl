{{/*
Shared naming and labels.

Every resource is named "<release>-<service>" so two releases can coexist in one
cluster, and carries the standard Kubernetes recommended labels so Argo CD and
kubectl selectors group them sensibly.
*/}}

{{- define "plexus.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{/* Release-scoped base name. Avoids "plexus-plexus" when the release is named
     after the chart, which is the common case. */}}
{{- define "plexus.fullname" -}}
{{- if eq .Release.Name .Chart.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{/* Common labels, applied to every object. */}}
{{- define "plexus.labels" -}}
app.kubernetes.io/name: {{ include "plexus.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: plexus
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{/*
Per-component selector labels.

Usage: {{ include "plexus.selectorLabels" (dict "root" $ "component" "frontend") }}

Selector labels must stay stable: they are immutable on a Deployment's
spec.selector, so anything that changes between releases (chart version, image
tag) has to be kept out of here.
*/}}
{{- define "plexus.selectorLabels" -}}
app.kubernetes.io/name: {{ include "plexus.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* Resource name for one component, e.g. "plexus-einvoice-mcp". */}}
{{- define "plexus.componentName" -}}
{{- printf "%s-%s" .root.Release.Name .component | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Full image reference for one of our own images.

Usage: {{ include "plexus.image" (dict "root" $ "image" .Values.frontend.image) }}
*/}}
{{- define "plexus.image" -}}
{{- printf "%s/%s:%s" .root.Values.imageRegistry .image.name .image.tag -}}
{{- end -}}

{{/* Name of the Secret holding credentials, whether we created it or not. */}}
{{- define "plexus.secretName" -}}
{{- .Values.secrets.name -}}
{{- end -}}

{{/* In-cluster Postgres DSN, with the password left as a $(VAR) reference.
     Kubernetes expands $(POSTGRES_PASSWORD) from another env var in the same
     container, which keeps the password out of the ConfigMap and out of Git
     while still handing the app a single DATABASE_URL. */}}
{{- define "plexus.databaseUrl" -}}
{{- printf "postgresql://%s:$(POSTGRES_PASSWORD)@%s-postgres:%v/%s" .Values.postgres.user .Release.Name .Values.postgres.port .Values.postgres.database -}}
{{- end -}}
