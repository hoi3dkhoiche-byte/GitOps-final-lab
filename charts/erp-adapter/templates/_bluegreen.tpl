{{/* Reuse the existing pod spec to keep resources/probes/security/secret references aligned. */}}
{{- define "erp.uiVersionedConfigName" -}}
metasfresh-ui-config-{{ include "erp.frontendConfig" (dict "Values" (dict "ui" (dict "config" .))) | replace "\r\n" "\n" | sha256sum | trunc 32 }}
{{- end -}}
