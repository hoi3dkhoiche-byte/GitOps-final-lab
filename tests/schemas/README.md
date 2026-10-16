# Vendored validation schema

Rollout v1alpha1 OpenAPI schema extracted with documentation-only `description` fields removed from https://raw.githubusercontent.com/argoproj/argo-rollouts/v1.10.1/manifests/crds/rollout-crd.yaml

Upstream CRD SHA256: `1562decc7b3720c31cbe382eeb62b6fbfd236f8e81a1f98644a9774d1e7d7933`.
Controller: v1.10.1; Helm chart: 2.43.7. Source license: Apache-2.0
(https://github.com/argoproj/argo-rollouts/blob/v1.10.1/LICENSE).
Validate locally; never install a CRD merely to run tests.

The pinned Helm chart removes these descriptions too; validation checks exact schema equality with the rendered chart.
Chart archive SHA256: `166506174f4be91ed2758fccbca340e209cba35aa72ac08b5863a7b797942487`.
