# Blue-Green UI on kubernetes-test

Status: local implementation for review. Nothing in this runbook has been executed against a cluster.
All cluster mutation commands below are **future operator steps**, after approval and the gates below.
Do not run the whole document as a script. Stop at each validation checkpoint.

## Scope and evidence

Only metasfresh UI changes. API/Core/database/PVC/Secret values stay unchanged.
No Vault/ESO, Origin rewriting, cross-site bypass, migration Job, routing plugin or automated promotion.
The source checkout inspected was `metasfresh` at `33b51b6924becca46547397b41298ea6463b55ea`.
Its existing edit to `metasfresh-gitops/environments/lab/values-lab.yaml` was preserved.

The earlier supplied **snapshot, not freshly verified live state**, recorded:

| Item | Snapshot / intended integration |
| --- | --- |
| Context | `kubernetes-test-admin@kubernetes-test`, Kubernetes v1.35.3 |
| ERP Application | `argocd/metasfresh-erp-test`, project `default`, manual sync |
| Source | `https://github.com/hoi3dkhoiche-byte/GitOps-final-lab.git`, branch `kubernetes-test`, path `charts/erp-adapter` |
| Helm | release `metasfresh-erp-test`, namespace `erp`, base `values.yaml` then chart-relative `values-kubernetes-test.yaml`; no inline parameters in snapshot |
| UI | Deployment/Service `metasfresh-ui`, 1 replica; runtime `/config.js` |
| UI image | `10.60.50.30/metasfresh/metas-frontend@sha256:c94094ff2d565bf8b40a72314ea76cca547ea29825a2ee815ada69c2707fb766` |
| API image | `10.60.50.30/metasfresh/metas-api@sha256:1364ad06166a8b8a830e9a84c10cf20ce404c3e3f5915a273f87469ac0d743c6` |
| Core image | `10.60.50.30/metasfresh/metas-app@sha256:c4327743ef50077590878558b8dd94c86391c56d806c9525cde1fdb5be4d5cd3` |
| Traffic | HAProxy class `haproxy-test`, active `erp-test.lab.internal`, private LB `10.60.31.91` |
| HAProxy | chart 1.54.0, controller `haproxytech/kubernetes-ingress:3.2.14` in snapshot |
| Backend dependencies | API -> Core; external PostgreSQL/RabbitMQ/search. These paths/policies are unchanged. |
| Secrets | References only: `harbor-pull`, `erp-properties-trial`, `erp-rabbit-secret`, active TLS `erp-origin-tls` |
| Rollouts | CRDs/controller absent in snapshot; current installation state **unverified** |

Actual owner of `metasfresh-erp-test` remains **unverified**. The existing
`platform/argocd/application-erp.yaml` describes a different Application and is unchanged.
Do not point the live Application at this feature branch or introduce another owner.

## States and traffic

Set only `ui.blueGreen.phase` in `charts/erp-adapter/values-kubernetes-test.yaml`.
The default is `disabled`; other environments also stay disabled.

| Phase | Legacy Deployment/Service/config | Rollout | Active `/` | Preview `/` |
| --- | --- | --- | --- | --- |
| disabled | retained | absent | `metasfresh-ui` | absent |
| prepare | retained, frozen | same digest/config as legacy | `metasfresh-ui` | `metasfresh-ui-preview` |
| cutover | retained, frozen | same initial revision | `metasfresh-ui-active` | `metasfresh-ui-preview` |
| steady | retired with reviewed prune | future UI releases | `metasfresh-ui-active` | `metasfresh-ui-preview` |

Both hosts: `/rest/api` and `/stomp` -> `metasfresh-api:8080` -> existing backend.
UI calls use relative `/rest/api` and `/stomp` on the browser's current hostname.
HAProxy -> named Service port 80 -> named pod targetPort `http` -> UI port 80.
Rollouts injects `rollouts-pod-template-hash` into the two Service selectors.
No traffic-routing plugin is used. Legacy pods use `app=metasfresh-ui`; Rollout pods use
`app=metasfresh-ui-bluegreen`, including topology spread and the additional ingress NetworkPolicy.

Revision 1 can immediately become active on the **new Service**, despite manual promotion being
configured. In prepare, users still reach the legacy Service. This is why migration is separate
from later releases. Rollout and legacy pod specs share the existing helper; probes, resources,
termination grace (60 seconds), scheduling and pull-secret references are preserved.
HPA/PDB must remain disabled for this first implementation when Blue-Green is enabled.

## Deployment gates: verify before any installation/sync

1. Verify context and cluster identity against the approved test environment. Capture current
   Application source/Helm values order, project permissions, parent ownerReferences, tracking
   annotations and managedFields managers. Find and edit its actual declarative owner.
   Check additional parameters/inline values have not changed effective values. Do not print
   kubeconfig, Secret objects, credentials or arbitrary Helm values that could contain secrets.
2. Compare the current Deployment pod templates, image specs and Pod `imageID` with Git.
   Confirm RS/Pod ownerReferences and Argo tracking/field ownership. Review replicas, node
   selectors, taints/tolerations, resources, probes and termination. Reconcile drift before
   using `migrationBaseline`; do not simply change that guard to bypass drift.
3. Inspect allocatable versus **requested** CPU/memory on eligible app/platform nodes, quotas,
   LimitRanges and topology constraints. Metrics alone do not prove scheduling capacity.
   With the current UI requests, prepare adds 200m/256Mi for one UI replica; future steady
   releases need old + new replicas concurrently. A pending revision plus an older delayed
   revision can need more; serialize releases until the previous scale-down completes.
   Controller proposal: one platform replica, requests 100m/128Mi, limits 500m/512Mi.
   Platform node label/taints and image pull from quay.io are **unverified**.
4. Confirm actual IngressClass/controller, publishService/private LB, endpoints, readiness,
   DNS resolution, TLS termination, annotations, rewrite behavior and WebSocket upgrade/timeouts.
   Live HAProxy Application had extra inline publishService/CRD-job scheduling settings compared
   with its bootstrap manifest; this patch intentionally does not reconcile that unrelated drift.
5. Provision/verify preview DNS `erp-test-preview.lab.internal` and a certificate SAN covering it.
   The proposed reference is **`erp-test-preview-tls`**, independently verified/provisioned by
   the existing TLS process. This patch creates no Secret and assumes no coverage from active TLS.
   Preview annotations inherit active ingress annotations: review whether any are host-specific.
6. Verify the API's allowed WebSocket Origin and actual browser cookies/session/CORS/CSRF behavior.
   Separate hostname means separate browser origin and normally separate host-only cookies/storage.
   Even relative `/stomp` requests carry the preview Origin; they may be rejected. The source
   defaults constrain allowed Origin to the configured frontend URL. If rejected, **stop cutover**;
   supporting preview would need a separately approved design. Do not rewrite Origin, enable
   cross-site globally or change API/DB as an implicit part of this UI release.
7. Establish active-host business baseline and preview test data/permissions. Preview login and
   writes hit the **same API/database as active users**: creates/edits/deletes, notifications and
   background jobs can affect shared data. Use approved test records and explicit cleanup.
8. Verify registry access for both current and rollback digests; retain images, immutable configs
   and their provenance for the rollback window. A readiness 200 only checks HTTP reachability.

Useful read-only commands on the bastion (run only after selecting the approved context):

```bash
kubectl config current-context
kubectl -n argocd get application metasfresh-erp-test -o jsonpath='{.spec.source.repoURL}{"\n"}{.spec.source.targetRevision}{"\n"}{.spec.source.path}{"\n"}{.spec.source.helm.releaseName}{"\n"}{.spec.source.helm.valueFiles}{"\n"}{.metadata.ownerReferences}{"\n"}{.metadata.managedFields[*].manager}{"\n"}'
kubectl -n erp get deployment metasfresh-ui metasfresh-api metasfresh-core
kubectl -n erp get pods -o custom-columns=NAME:.metadata.name,OWNER:.metadata.ownerReferences[0].name,IMAGE:.spec.containers[*].image,IMAGE_ID:.status.containerStatuses[*].imageID
kubectl -n erp get service metasfresh-ui metasfresh-api metasfresh-core -o yaml
kubectl -n erp get endpointslice -l kubernetes.io/service-name=metasfresh-ui -o yaml
kubectl -n erp get ingress metasfresh-ingress -o yaml
kubectl get ingressclass haproxy-test -o yaml
kubectl -n erp get resourcequota,limitrange
kubectl get nodes -L cmccloud-k8s-nodegroups
kubectl describe nodes
kubectl get crd rollouts.argoproj.io
```

Inspect TLS using the served public certificate/approved certificate inventory, never by dumping
TLS Secret data. Deployment manifests may contain unrelated literal environment values: extract
only the pod spec fields needed for comparison; do not paste credentials into evidence.

## Platform prerequisite and Application integration

The proposed platform Application is
`clusters/kubernetes-test/bootstrap/argo-rollouts-application.yaml`: official Helm chart **2.43.7**,
controller **v1.10.1**, no automated sync/finalizer, dashboard disabled. It has its own namespace
and cluster RBAC. Review AppProject permissions, CRD ownership and existing controllers first.
If Rollouts is already installed, use that approved owner/version after compatibility/schema review;
do not install a competing controller. A version pin is not evidence of cluster compatibility.

After approval, the operator registers this platform Application through the established bootstrap
owner, reviews its diff, and syncs **only the platform Application** first. Its ServerSideApply option
avoids the large-CRD last-applied annotation limit. It does not change ERP sync options.

```bash
argocd app diff argo-rollouts-test
argocd app sync argo-rollouts-test
kubectl wait --for=condition=Established crd/rollouts.argoproj.io --timeout=120s
kubectl -n argo-rollouts rollout status deployment/argo-rollouts --timeout=180s
kubectl -n argo-rollouts get pods
```

Confirm CRDs, controller image, readiness, leader election and permissions to manage ERP
Rollouts/ReplicaSets/Services; review controller logs for errors. Install a matching Rollouts
kubectl plugin on the operator machine through its approved process before using commands below.
Do not sync an ERP Rollout until these checks pass. Do not skip missing-resource validation.

Merge `docs/bluegreen/erp-test-application-fragment.yaml` into the **existing** Application owner.
It is a spec fragment, not an applyable Application. Preserve any existing ignore rules and sync
options. It ignores exactly `/spec/selector/rollouts-pod-template-hash` on the two named ERP Services.
`RespectIgnoreDifferences=true` is needed to preserve that ignored field during sync, not just diff.
It only takes effect for existing resources; on first creation Git supplies only the stable app label.
Do not ignore all selectors/Services or hardcode a ReplicaSet hash.
Keep repo/path/release/values/targetRevision as verified above, with manual sync.

## First migration: separate, reviewed phase changes

1. Merge/review the code with phase **disabled**. Render and diff against current desired manifests;
   no existing resource should change. All live gates and platform/Application prerequisites must pass.
2. In a distinct reviewed change, set **prepare**. Freeze the current UI digest/config. The supplied
   `migrationBaseline` pins the surveyed image and URLs; if live differs, resolve/review the baseline
   first. The release guard also checks legacy Deployment/Service/config stayed identical.
   Before syncing, check `argocd app diff metasfresh-erp-test`: legacy and active ingress must be unchanged.
3. Sync prepare manually. Verify new Rollout/RS ownership, isolated selectors, both new Service hashes,
   ready EndpointSlices and preview TLS. The first Rollout revision may already be fully promoted.
   Run the entire browser acceptance matrix below. Confirm active traffic still reaches legacy.
4. In another reviewed change set **cutover**. Diff must change only the active ingress root backend
   compared with prepare. Keep legacy running. After manual sync, test active login/REST/STOMP,
   old tabs and new sessions; inspect HAProxy errors and EndpointSlices during propagation.
5. Observe for an agreed period with functional and operational evidence. Then separately set
   **steady**. Review prune list: only legacy Deployment `metasfresh-ui`, Service `metasfresh-ui`,
   and mutable ConfigMap `metasfresh-frontend-config` should be retired. Use an approved manual prune
   after validating the full Application diff; do not prune API/Core/PVC or versioned ConfigMaps.
   Retained generic/legacy NetworkPolicy rules are harmless and remain unchanged.

```bash
argocd app diff metasfresh-erp-test
argocd app sync metasfresh-erp-test
kubectl argo rollouts -n erp get rollout metasfresh-ui-bluegreen
kubectl -n erp get service metasfresh-ui-active metasfresh-ui-preview -o yaml
kubectl -n erp get endpointslice -l kubernetes.io/service-name=metasfresh-ui-active -o yaml
```

Migration rollback while legacy is still present: return **cutover -> prepare** in Git and sync the
reviewed change. This restores only root routing to the healthy legacy UI. Keep the Rollout for
investigation. After legacy is retired, this routing rollback is unavailable; use the release
rollback procedure below. Do not switch steady -> disabled/cutover and assume the old UI still exists.

## Routine UI image release (steady only)

1. Confirm the previous release is stable and old delayed replicas have settled. Record the good
   Git SHA, UI digest, full Rollout pod template, config name/content and ReplicaSet revision.
2. Use a reviewed manual UI-only digest change in **`charts/erp-adapter/values-kubernetes-test.yaml`**.
   Record the successful build run/source commit, tested image digest and scan evidence in the PR.
   Do not update API/Core digests or run the application's all-component promotion workflow.
   Its existing `deploy-app.yml` renders lab values and `ci/update_gitops.py` updates all three base
   values/`versions.yaml`; it is not a UI-only test-cluster release path. `versions.yaml` remains
   the earlier all-component build record, not authoritative for a later UI-only release.
   The new GitOps validation workflow renders the correct overlay and understands Rollout resources;
   it does not build, push, open PRs or deploy. Build provenance remains a required reviewer gate.
3. Current config is rendered into an immutable hash-named ConfigMap. Before any approved config
   change, append the previous `ui.config` object to `ui.blueGreen.configHistory`, keeping all configs
   needed by active/old RS and cold rollback. Configs are in desired manifests, so Argo prune cannot
   remove them during ordinary releases. Duplicate config content produces one ConfigMap.
   This first implementation restricts current URLs to same-origin `/rest/api` and `/stomp`;
   changing routing/auth behavior requires a separate reviewed change to that guard.
4. Run local validation and compare before/after renders. Merge only the intended UI release into
   `kubernetes-test`, then manually sync. New revision becomes preview, active stays on the good RS.
   No `autoPromotionSeconds`, analysis-based promote, rollbackWindow or traffic plugin is configured.
5. Run browser/business tests on preview, then the operator explicitly promotes:

```bash
kubectl argo rollouts -n erp get rollout metasfresh-ui-bluegreen
kubectl argo rollouts -n erp promote metasfresh-ui-bluegreen
kubectl argo rollouts -n erp get rollout metasfresh-ui-bluegreen --watch
```

Do not use `--full` to bypass gates. Verify active Service hash/endpoints now identify the approved
image, and run active-host tests. Default `scaleDownDelaySeconds: 600` retains old replicas for
propagation/rollback; it is configurable (minimum 30). `revisionHistoryLimit: 5` retains RS history,
**not five running stacks**. Monitor the actual RS replica counts; delay alone is not a guarantee.

Mandatory field-ownership acceptance: record active/preview hash and endpoints after promotion;
wait for Rollout stable, sync the same Application revision again, and verify hashes, endpoint
imageIDs and routing stay unchanged. Inspect Argo diff and managedFields. If Argo removes the hash
or routes both revisions, stop further releases and repair integration with the Application owner.
This behavior is a live gate; offline render tests cannot prove controller reconciliation.

## Release rollback and Git correction

Always identify the good **full pod template/config**, not just a revision number. Commands below
use shell variable `GOOD_REVISION` supplied by the operator after inspecting Rollout/RS history.
Do not copy an example number, patch Service hashes manually, or assume readiness means business health.

- **Before promote, update in progress:** active is still good. Abort the candidate, verify routing
  and endpoints, then revert the UI digest/config in Git and sync. Abort changes controller state;
  it does not correct the desired manifest. Keep configHistory entries during the correction.

```bash
kubectl argo rollouts -n erp abort metasfresh-ui-bluegreen
```

- **After promote, Blue still running within the delay:** revert the desired Rollout template to
  the exact good revision. Prefer an expedited reviewed Git correction followed by sync. In an
  approved incident procedure, `undo` can restore it immediately while the Git correction is
  prepared. Rollouts can fast-track a return to a still-scaled old blue-green RS; verify actual
  active hash/endpoints and business behavior, never assume the command alone completed rollback.
  Hold manual sync/any external image writer until Git contains the good digest/config; merge the
  correction before resuming reconciliation. Do not use abort as the default for a completed release.

```bash
# Set GOOD_REVISION to the verified good RS revision, then:
kubectl argo rollouts -n erp undo metasfresh-ui-bluegreen --to-revision "$GOOD_REVISION"
kubectl argo rollouts -n erp get rollout metasfresh-ui-bluegreen --watch
```

- **After Blue scaled to zero, RS still exists:** restoration needs scheduling, image pull and
  startup. Revert the complete good template in Git, sync, wait for the good preview to become
  available, test and manually promote if paused. The bad version may remain active during this
  cold recovery. Budget recovery time; it is not an instant rollback.
- **RS history already garbage-collected:** restore the good digest/config/template from reviewed
  Git history as a new candidate. Retained ConfigMaps and registry images make pod recreation
  possible. Use the same preview/test/promote process. Missing image/config/capacity blocks recovery.
- **Update promoted but still progressing:** inspect controller state and active/stable revisions;
  use the explicit good-template restoration above. An abort is only appropriate if the controller
  still has the intended good stable revision and operator has verified that behavior.

After any rollback, the desired test overlay must point to the good image/config, the bad desired
commit must be reverted/superseded, and Argo must be synced to that corrected Git revision. Verify
another sync cannot reintroduce the bad candidate. Preserve configs used by either RS until the
rollback window closes. Config GC is a separate reviewed operation after checking all RS references
and cold-rollback commitments; `check_ui_release.py` deliberately rejects history removal in normal
release PRs. Do not bypass that guard in an image release.

## Browser acceptance and static-asset limitation

Source evidence (not browser proof):

- `frontend/index.html` loads `/config.js` at runtime; the pod mounts it from a ConfigMap using
  subPath. New pod revisions bind an immutable config name; a mutable shared file is not relied on.
- `docker-builds/Dockerfile.frontend` builds with `webpack.docker.js` and copies only that build's
  `dist` into nginx. The bundle name includes `[chunkhash]`; other asset names can use fixed
  `ab12zz` suffixes or unchanged logo names. No explicit `chunkFilename` or old-asset retention
  is configured. A plugin dynamic import in App.js is commented out; shipped runtime/vendor/plugin
  behavior and actual lazy-loaded chunks have not been proven from browser/network evidence.
- `docker-builds/nginx/default.conf` has `try_files $uri /index.html` and no explicit cache headers.
  Missing JS can return HTML with status 200 instead of 404, causing MIME/syntax/chunk errors.
  HTML/config cache behavior depends on nginx defaults and any upstream proxy/browser cache.
- After Service cutover, old Blue still running does **not** make old hashed asset URLs available
  via active Service. Cached old HTML, delayed imports and tabs held open can request removed files.

Required matrix on both active and preview: login/logout, session expiry/re-login, read REST calls,
approved write and verification, errors/CSRF behavior, STOMP connect and actual business event,
reconnect after connection loss, browser refresh on deep links, hard refresh, cache-enabled refresh,
multiple tabs, and a pre-existing tab opened before promotion that navigates after promotion/rollback.
Inspect actual Origin, cookies/SameSite/Secure/Domain/Path, response cache headers, JS content types
and console errors. Do not export tokens/cookies into the release report.

Concrete remediation if these tests fail: block promote; prepare a separately reviewed UI image
that serves `index.html` and `config.js` with revalidation/no-store, returns a real failure for missing
static assets, and retains the previous version's hashed assets (or uses an approved versioned asset
store) for the tab/rollback window. Hash all changing asset filenames before applying immutable cache
headers. Review third-party/plugin assets as well. Until that image is built and browser-tested,
use an explicit maintenance/reload procedure agreed with users if necessary; do not silently discard
unsaved form data. This GitOps patch does not rebuild nginx or claim zero downtime.

## Local review and validation

Requires Helm, Python, PyYAML and jsonschema. Commands run from the GitOps repository:

```bash
python -m pip install -r tests/requirements-bluegreen.txt
python tests/test_bluegreen.py --previous fa1798247db0a79dcdf32b432af0e00da15d3513
# Optional platform chart validation (download only, no install):
helm pull argo-rollouts --repo https://argoproj.github.io/argo-helm --version 2.43.7 --destination .rendered
python tests/test_bluegreen.py --previous fa1798247db0a79dcdf32b432af0e00da15d3513 --platform-chart .rendered/argo-rollouts-2.43.7.tgz
python scripts/check_ui_release.py .rendered/bluegreen/test-prepare.yaml .rendered/bluegreen/test-cutover.yaml
git diff --check
git diff -- charts/erp-adapter
git status --short
```

For future PRs, replace `--previous` with the actual target-branch base SHA. The fixed initial
`--baseline` exercises the migration contract using the surveyed UI fixture; `--previous` separately
checks the **actual** desired renders. Release `metasfresh-erp-test`, namespace `erp`, values order
is base then chart-relative test values. Existing lab/trial overlays use their Application release
`erp`, including lab then runtime-trial order. The local Rollout schema is vendored from the pinned
release and checked against the pinned chart; these tests do not install CRDs or contact Kubernetes.
Artifacts under `.rendered/bluegreen` include phase YAML and a test report; they are gitignored.
`git diff` does not display untracked new files: review the new paths shown by `git status` too.

## References

- [Argo Rollouts Blue-Green behavior](https://argo-rollouts.readthedocs.io/en/stable/features/bluegreen/)
- [First migration and initial revision](https://argo-rollouts.readthedocs.io/en/stable/migrating/)
- [Rollback and still-scaled ReplicaSets](https://argo-rollouts.readthedocs.io/en/stable/features/rollback/)
- [Argo CD RespectIgnoreDifferences](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/#respect-ignore-differences-configs)
- [Pinned chart release](https://github.com/argoproj/argo-helm/releases/tag/argo-rollouts-2.43.7)
