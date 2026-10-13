# HAProxy Ingress GitOps

This static manifest adopts HAProxy on the existing CMC Cloud lab cluster.

Chart: kubernetes-ingress 1.54.2
Namespace: ingress-system
Argo CD application: haproxy-ingress
Synchronization: manual

Current environment:
- Private ELB VIP: 10.60.20.173
- HTTPS NodePort: 31443
- Health check NodePort: 32042
- External traffic policy: Local
- Source range: 10.60.20.100/32

The ELB ID and ELB address annotations are owned by the
cloud controller and are intentionally not included.

Do not reuse this static manifest unchanged on a new cluster.
Subnets, ELB flavor, source ranges, node groups and relevant
network configuration must be validated for each environment.

Do not enable automated prune, replace or force synchronization
without a reviewed migration plan.

The HAProxy CRD bootstrap Job is not managed by this Application.
Check CRD dependencies separately before a new-cluster installation.

Before any manual synchronization:
- Review Argo CD Diff.
- Confirm the LoadBalancer Service has no unexpected changes.
- Confirm IngressClass controller is unchanged.
- Check Deployment Pod template and RBAC.
- Verify ELB identity, VIP, health checks and backend membership.

After synchronization:
- Verify Deployment is 2/2 Ready.
- Verify both HTTPS endpoints.
- Verify original ELB VIP and ID are unchanged.
- Verify ERP HTTPS connectivity through the intended path.
