# Monitoring CRD Bootstrap — CMC Cloud Final Lab

## Purpose

Bootstrap Prometheus Operator CRDs before installing the
Prometheus Operator and monitoring custom resources.

This directory is NOT an Argo CD Application source.

## Version

- Chart: kube-prometheus-stack
- Chart version: 92.1.0
- Kubernetes version validated against: 1.35.3
- CRD count: 10
- Source: https://prometheus-community.github.io/helm-charts

CRDs were extracted using:

helm show crds kube-prometheus-stack \
  --repo https://prometheus-community.github.io/helm-charts \
  --version 92.1.0

## Verification

From the crds directory:

sha256sum -c SHA256SUMS

kubectl create --dry-run=client --validate=false \
  -f monitoring-crds-92.1.0.yaml -o name

Expected: 10 CustomResourceDefinition resources.

## Installation policy

1. Bootstrap CRDs only on the explicitly selected NEW cluster.
2. Verify kubeconfig, cluster identity, and Kubernetes version.
3. Verify CRD checksum before installation.
4. Install CRDs before Prometheus Operator custom resources.
5. Wait for all 10 CRDs to become Established.
6. Review CRD schema changes before upgrades.

Do not apply this file to the existing lab cluster merely
to adopt CRDs into GitOps.

## Ownership and safety

- CRDs are cluster-scoped shared infrastructure.
- Do not enable automated prune or deletion of these CRDs.
- Never use kubectl replace --force on active CRDs.
- CRD deletion can delete the corresponding custom resources.
- Operator-generated StatefulSets and PVCs are not managed here.

## Dependencies after CRD bootstrap

Admission certificate bootstrap must prepare:
- monitoring-admission TLS Secret
- required certificate Job RBAC
- webhook configurations with matching CA bundles

The operator, monitoring rules, Prometheus and Alertmanager
custom resources must be deployed in the correct order.

Additional dependencies on a new cluster include:
- Grafana admin credentials
- Prometheus additional scrape configuration Secret
- Alertmanager configuration Secret
- StorageClass and persistent storage provisioning

Never commit TLS private keys or plaintext credentials.

## Current lab validation

- 10 CRD names matched
- Served API versions matched
- 10/10 CRDs Established
- Normalized OpenAPI schema structures matched
- Kubernetes client dry-run succeeded

This does not replace validation on the target new cluster.
