# Blue-Green UI implementation handoff

Patch status: local implementation and validation complete. The user has authorized committing and publishing the feature branch. **No cluster deployment has been performed.**

- Repository/worktree: `D:\Final. Lab\GitOps-final-lab` (original clean working tree, no extra worktree needed).
- Branch: `feature/bluegreen-ui-test` created from freshly fetched `origin/kubernetes-test`.
- Implementation base commit: `fa1798247db0a79dcdf32b432af0e00da15d3513`.
- No repository/ancestor AGENTS.md was found during inspection.
- The unrelated existing source-repo edit in `metasfresh-gitops/environments/lab/values-lab.yaml` remains untouched.
- No Secret values, credentials, private keys or kubeconfig were read or printed.

## Design

`disabled` preserves existing resources; `prepare` adds an isolated Rollout with the same image/config
while active traffic remains legacy; `cutover` switches only active `/` and retains legacy;
`steady` retires legacy after review. Default remains disabled.

API/Core/database behavior is unchanged. Promotion is manual; old RS scale-down delay defaults to
600 seconds, history limit 5. ConfigMaps are immutable, named by content hash and retained explicitly
in desired manifests. New UI selectors cannot match the legacy Deployment. No traffic-routing plugin.

The ERP Application remains owned by its existing source, which is still unknown. Only a merge
fragment is supplied; the unrelated production Application is untouched. Separate platform
Application is pinned and has no automated sync. See [runbook](RUNBOOK.md) for all operational steps.

## Files and purpose

| File | Purpose |
| --- | --- |
| `.github/workflows/validate-ui-bluegreen.yaml` | PR validation for kubernetes-test; correct overlay, Rollout-aware, no deployment. |
| `charts/erp-adapter/README.md` | Link implementation usage and runbook. |
| `charts/erp-adapter/values.yaml` | Disabled defaults, phase enum input, delay/history/config catalog. |
| `charts/erp-adapter/values-kubernetes-test.yaml` | Disabled test configuration; explicit preview TLS and pinned migration baseline. |
| `charts/erp-adapter/values.schema.json` | Types, allowed phase/options and rejection of contradictory/unsupported fields. |
| `charts/erp-adapter/templates/001-bluegreen-validation.yaml` | Require digest, baseline parity, same-origin routes and first-release constraints. |
| `charts/erp-adapter/templates/_bluegreen.tpl` | Content-derived ConfigMap names, stable across LF/CRLF. |
| `charts/erp-adapter/templates/rollout-ui.yaml` | Manual Blue-Green with isolated selector and existing pod settings. |
| `charts/erp-adapter/templates/bluegreen-config.yaml` | Immutable current/history ConfigMaps kept in desired manifests. |
| `charts/erp-adapter/templates/bluegreen-services.yaml` | Active/preview Services; hash selector belongs to Rollouts. |
| `charts/erp-adapter/templates/bluegreen-ingress.yaml` | Preview host/TLS; existing API/STOMP routes. |
| `charts/erp-adapter/templates/bluegreen-networkpolicy.yaml` | HAProxy ingress allowed for new UI selector. |
| `charts/erp-adapter/templates/deployment-ui.yaml` | Keep legacy except in steady. |
| `charts/erp-adapter/templates/service-ui.yaml` | Keep legacy except in steady. |
| `charts/erp-adapter/templates/frontend-config.yaml` | Keep legacy config except in steady. |
| `charts/erp-adapter/templates/ingress.yaml` | Only select active UI backend by migration phase. |
| `clusters/kubernetes-test/bootstrap/argo-rollouts-application.yaml` | Manual platform prerequisite; chart 2.43.7/controller v1.10.1 pinned. |
| `docs/bluegreen/erp-test-application-fragment.yaml` | Merge into actual test Application owner; exact two hash ignores plus RespectIgnoreDifferences. |
| `docs/bluegreen/RUNBOOK.md` | Live gates, migration, routine releases, promotion, hot/cold rollback, config retention, browser/static asset risk. |
| `docs/bluegreen/IMPLEMENTATION-REPORT.md` | This handoff and file inventory. |
| `scripts/check_ui_release.py` | Structural UI-only change/phase/history-retention guard. |
| `tests/test_bluegreen.py` | Baseline render comparison, four phases, CRD/schema and negative/positive cases. |
| `tests/requirements-bluegreen.txt` | Pinned local/CI validation dependencies. |
| `tests/schemas/rollout-v1.10.1.json` | Offline validation schema matching pinned chart CRD. |
| `tests/schemas/README.md` | Schema origin, transformation and source/archive checksums. |
| `tests/schemas/LICENSE-argo-rollouts` | License for the vendored schema. |

## Executed local validation

Baseline was rendered and saved **before chart edits** in `.rendered/bluegreen-baseline`.
Tests reconstruct that exact Git base with checkout filters and compare parsed resource structures.
The old helper computes a raw-text checksum, so Git LF versus Windows CRLF must be consistent when
constructing the baseline; the new config-name hash explicitly normalizes line endings.

Full suite passed with local **Helm 4.3.0**, and again using downloaded, checksum-verified
**Helm 3.16.4** (the CI version), on Python 3.14.8. CI is configured for Python 3.12 but has not been
run on GitHub. Helm 3.16.4 was injected only into the validation subprocess environment.

Command: `python tests/test_bluegreen.py --previous fa1798247db0a79dcdf32b432af0e00da15d3513 --platform-chart .rendered/argo-rollouts-2.43.7.tgz`

```text
Baseline: fa1798247db0a79dcdf32b432af0e00da15d3513
PASS disabled == base: test (18 resources)
PASS disabled == base: lab (19 resources)
PASS disabled == base: trial (18 resources)
PASS prepare: CRD schema, pod spec parity, selectors, traffic, backend/PVC/Secret references/policies unchanged (24 resources)
PASS cutover: CRD schema, pod spec parity, selectors, traffic, backend/PVC/Secret references/policies unchanged (24 resources)
PASS steady: CRD schema, pod spec parity, selectors, traffic, backend/PVC/Secret references/policies unchanged (21 resources)
PASS configurable delay/history/preview hostname and TLS; stable config hash; 14 unchanged resources fingerprinted
PASS release guard/config retention/CRD negative test; 15 invalid configurations rejected
PASS actual PR desired manifests vs previous: UI-only guard
PASS pinned platform chart lint/render; shipped CRD matches vendored schema
```

Also passed: standalone `check_ui_release.py` on prepare -> cutover, and `git diff --check`.
Lint used `--strict`; the only Helm informational notice was the optional chart icon recommendation.
The rendered platform controller image is `quay.io/argoproj/argo-rollouts:v1.10.1`; its shipped
Rollout schema equals the vendored schema. No cluster CRD installation was needed for validation.

## Invariance evidence

Test overlay disabled: all **18 resources** equal baseline. Lab: all **19** equal baseline.
Lab + runtime-trial: all **18** equal baseline, with the existing release name/value order.
Prepare/cutover render 24 resources, steady 21. Across all enabled phases, **14 resources** are
structurally identical to the base: API/Core Deployments and Services, both PVCs, all seven existing
NetworkPolicies and the ServiceAccount. This comparison includes all backend Secret references,
images, env, resources, mounts, probes, scheduling and termination fields.

`prepare` also preserves the full legacy Deployment/Service/ConfigMap and active Ingress.
`cutover` changes only root backend in active Ingress compared with prepare. `steady` removes only
those three legacy UI resources. New Rollout pod template differs from legacy only in app/topology
selectors and versioned config volume name. Current/history config retention is tested; the release
guard rejects history pruning, backend changes and skipped migration phases.

Review machine-readable fingerprints in `.rendered/bluegreen/invariance.json` and complete phase
renders in `.rendered/bluegreen`. Before/after fingerprints are equal for each of those 14 resources.
These are local generated artifacts, intentionally gitignored.

## Unverified / deployment gates

Current live state was not refreshed in this coding stage; previous supplied outputs are a snapshot.
Actual test Application owner/field ownership, current spec/imageID drift, capacity/quotas/taints,
controller availability/compatibility, preview DNS/TLS SAN, WS Origin and cookies/session/CORS/CSRF,
and browser/business behavior remain **unverified**. Preview writes affect the shared backend.
Re-sync after promote must preserve Service hashes; only a live test can prove that reconciliation.

Source inspection found content-hashed main bundle but no old-asset retention or explicit HTML/config
cache policy. Old tabs can request assets absent from the new image, and nginx SPA fallback can
return HTML for missing JS. The runbook provides test gates and concrete remediation; zero downtime
is not claimed. Rollback is fast only when the good RS still runs; cold rollback must restore pods,
then validate/promote. Every rollback must correct Git desired image/config to prevent recurrence.

## Review and next step

```powershell
Set-Location 'D:\Final. Lab\GitOps-final-lab'
git status --short
git diff --check
git diff -- charts/erp-adapter
Get-Content .rendered/bluegreen/review.patch
```

The combined review patch includes tracked changes **and new untracked files** without staging
anything. Review this patch/runbook first. Publishing the feature branch is authorized. PR/merge and each platform/migration step remain
separate actions with live gates; no targetRevision change is proposed.
