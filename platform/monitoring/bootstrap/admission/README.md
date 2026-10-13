# Prometheus Operator Admission Bootstrap

## Environment

Project: CMC Cloud Final Lab

Pinned versions:
- kube-prometheus-stack: 92.1.0
- kube-webhook-certgen: 1.8.9
- Kubernetes: 1.35.3

## Purpose

Provision Prometheus Operator admission certificates,
RBAC, and webhook configurations on a NEW Kubernetes cluster.

These manifests are NOT an Argo CD Application source.

Do not automatically synchronize the admission bootstrap Jobs.

## Manifest inventory

1. admission-rbac.yaml
   - ServiceAccount monitoring-admission
   - ClusterRole monitoring-admission
   - ClusterRoleBinding monitoring-admission
   - Role monitoring-admission
   - RoleBinding monitoring-admission

2. admission-create-job.yaml
   - Job monitoring-admission-create

3. admission-webhooks.yaml
   - MutatingWebhookConfiguration monitoring-admission
   - ValidatingWebhookConfiguration monitoring-admission

4. admission-patch-job.yaml
   - Job monitoring-admission-patch

## Required deployment order

Before any installation:

- Select the NEW Kubernetes cluster explicitly.
- Verify its kubeconfig context, API endpoint, and identity.
- Confirm Kubernetes version and node readiness.
- Never run bootstrap Jobs against the existing lab cluster.

Deployment stages:

1. Create the monitoring namespace.
2. Install the ten version-pinned Monitoring CRDs.
3. Wait until all ten CRDs are Established.
4. Install admission RBAC.
5. Run the admission-create Job once.
6. Wait for the Job to complete.
7. Verify Secret monitoring/monitoring-admission contains:
   ca, cert, key.
8. Deploy Prometheus Operator Core and wait for readiness.
9. Prepare admission webhook manifests with caBundle
   populated from the new cluster's admission CA.
10. Register the webhook configurations.
11. Run the admission-patch Job and wait for completion.
12. Verify CA fingerprints, certificate validity,
    DNS SAN, Operator Endpoint, and webhook behavior.
13. Only then proceed with Monitoring Rules
    and Prometheus/Alertmanager custom resources.

## Critical CA safety

The admission-webhooks.yaml file contains empty caBundle
values because it originates from Helm chart rendering.

NEVER repeatedly apply this raw file to an active cluster.
That could overwrite the CA configured in the live webhooks.

Generate the CA-populated manifests during bootstrap using
the target cluster's monitoring-admission Secret.

The CA certificate may be included in the generated
webhook configuration. Never export or commit the private key.

The patch Job is for controlled certificate setup or renewal,
not automatic recurring Argo CD reconciliation.

## Certificate lifecycle

Certificate generator:
ghcr.io/jkroepke/kube-webhook-certgen:1.8.9

Certificate DNS names:
- monitoring-operator
- monitoring-operator.monitoring.svc

The currently validated lab uses a long-lived certificate.
This is not the recommended production lifecycle.

For production, use a reviewed certificate issuance and
rotation mechanism with an appropriately short validity period.

## Failure policy

Current failurePolicy is Ignore.

This allows monitoring-related API requests to continue if
the webhook is unreachable or unable to respond.

Review changing to Fail after confirming certificate
management, endpoint availability, and recovery procedures.

## Safety rules

- Do not run bootstrap on the existing cluster.
- Do not use automatic prune on Monitoring CRDs.
- Do not store TLS private keys in Git.
- Do not commit generated Secret contents.
- Do not automatically rerun certificate Jobs.
- Do not deploy webhook configurations with blank CA.
- Do not manage Operator-generated StatefulSets or PVCs.
- Verify the selected cluster before any write operation.

## Validation performed on original lab

- All 10 Monitoring CRDs Established.
- CRD names, served versions, and normalized schemas matched.
- Operator Endpoint was Ready.
- Admission CA matched all three webhooks.
- TLS chain and service hostname verification passed.
- All nine bootstrap resources passed Kubernetes client dry-run.

New-cluster end-to-end deployment is NOT yet tested.
