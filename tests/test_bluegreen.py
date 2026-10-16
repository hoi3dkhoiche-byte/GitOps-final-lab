"""Offline chart contract tests against the pre-implementation Git baseline."""
import argparse
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".rendered/python-deps"))
sys.path.insert(0, str(ROOT / "scripts"))
import yaml
from jsonschema import Draft7Validator
from check_ui_release import objects, errors

CONTRACT = None
BASE = "fa1798247db0a79dcdf32b432af0e00da15d3513"
VARIANTS = {
    "test": ("metasfresh-erp-test", ["charts/erp-adapter/values-kubernetes-test.yaml"]),
    "lab": ("erp", ["environments/lab/values-lab.yaml"]),
    "trial": ("erp", ["environments/lab/values-lab.yaml", "environments/lab/values-runtime-trial.yaml"]),
}


def run(args, cwd=ROOT, success=True):
    p = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if success and p.returncode:
        raise AssertionError(p.stdout + p.stderr)
    if not success:
        assert p.returncode, "invalid values unexpectedly accepted"
    return p.stdout


def snapshot(ref, target):
    # Read only chart and overlays, never secrets or a whole working directory.
    names = run(["git", "ls-tree", "-r", "--name-only", ref, "charts/erp-adapter", "environments/lab"])
    for name in names.splitlines():
        if name.startswith("charts/erp-adapter/") or name in {p for _, files in VARIANTS.values() for p in files}:
            dest = target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(subprocess.check_output(["git", "cat-file", "--filters", f"{ref}:{name}"], cwd=ROOT))


def render(root, variant="test", phase=None, extra=None, lint=True, success=True):
    release, files = VARIANTS[variant]
    flags = ["--namespace", "erp"]
    for file in files:
        flags += ["-f", str(root / file)]
    if phase and CONTRACT and root == ROOT and variant == "test":
        flags += ["-f", str(CONTRACT)]
    if phase:
        flags += ["--set", f"ui.blueGreen.phase={phase}"]
    if extra:
        flags += ["-f", str(extra)]
    chart = str(root / "charts/erp-adapter")
    if lint and success:
        run(["helm", "lint", chart, "--strict"] + flags)
    return run(["helm", "template", release, chart] + flags, success=success)


def obj(items, kind, name):
    return items[(kind, "erp", name)]


def strict_schema(schema):
    # Kubernetes rejects/prunes undeclared CRD fields. JSON Schema alone defaults
    # to allowing them. Keep free-form maps (metadata/labels) unrestricted.
    result = copy.deepcopy(schema)
    def walk(node):
        if isinstance(node, dict):
            if "properties" in node and not node.get("x-kubernetes-preserve-unknown-fields"):
                node.setdefault("additionalProperties", False)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(result)
    return result


def main():
    global CONTRACT
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default=BASE)
    parser.add_argument("--previous", help="Optional PR base SHA for UI-only change guard")
    parser.add_argument("--platform-chart", type=Path, help="Optional downloaded argo-rollouts-2.43.7.tgz")
    args = parser.parse_args()
    output = ROOT / ".rendered/bluegreen"
    output.mkdir(parents=True, exist_ok=True)
    validator = Draft7Validator(strict_schema(json.loads((ROOT / "tests/schemas/rollout-v1.10.1.json").read_text())))
    report = []
    with tempfile.TemporaryDirectory(prefix="bluegreen-") as temp:
        temp = Path(temp)
        base = temp / "base"
        snapshot(args.baseline, base)
        baseline_values = yaml.safe_load((base / "charts/erp-adapter/values.yaml").read_text())
        baseline_override = yaml.safe_load((base / "charts/erp-adapter/values-kubernetes-test.yaml").read_text())
        ui_image = {**baseline_values["ui"]["image"], **baseline_override["ui"]["image"]}
        ui_config = baseline_values["ui"]["config"]
        CONTRACT = temp / "contract.yaml"
        CONTRACT.write_text(yaml.safe_dump({"ui": {"image": ui_image, "config": ui_config,
            "blueGreen": {"migrationBaseline": {"image": ui_image["repository"] + "@" + ui_image["digest"], "config": ui_config}}}}), encoding="utf-8")
        baseline = {}
        for variant in VARIANTS:
            baseline[variant] = objects(render(base, variant))
            disabled = render(ROOT, variant, "disabled")
            assert objects(disabled) == baseline[variant], f"disabled drift: {variant}"
            (output / f"{variant}-disabled.yaml").write_text(disabled, encoding="utf-8")
            captured = ROOT / f".rendered/bluegreen-baseline/{variant}.yaml"
            if captured.exists():
                assert objects(captured.read_text(encoding="utf-8-sig")) == baseline[variant]
            report.append(f"PASS disabled == base: {variant} ({len(baseline[variant])} resources)")
        phases = {}
        for phase in ("prepare", "cutover", "steady"):
            rendered = render(ROOT, phase=phase)
            (output / f"test-{phase}.yaml").write_text(rendered, encoding="utf-8")
            current = phases[phase] = objects(rendered)
            roll = obj(current, "Rollout", "metasfresh-ui-bluegreen")
            validator.validate(roll)
            assert roll["spec"]["strategy"]["blueGreen"] == {
                "activeService": "metasfresh-ui-active", "previewService": "metasfresh-ui-preview",
                "autoPromotionEnabled": False, "scaleDownDelaySeconds": 600}
            assert roll["spec"]["revisionHistoryLimit"] == 5
            expected_pod = copy.deepcopy(obj(baseline["test"], "Deployment", "metasfresh-ui")["spec"]["template"])
            expected_pod["metadata"]["labels"]["app"] = "metasfresh-ui-bluegreen"
            expected_pod["spec"]["topologySpreadConstraints"][0]["labelSelector"]["matchLabels"]["app"] = "metasfresh-ui-bluegreen"
            cm_name = roll["spec"]["template"]["spec"]["volumes"][0]["configMap"]["name"]
            expected_pod["spec"]["volumes"][0]["configMap"]["name"] = cm_name
            assert roll["spec"]["template"] == expected_pod, "unexpected UI pod spec drift"
            cm = obj(current, "ConfigMap", cm_name)
            assert cm["immutable"] is True
            canonical_config = cm["data"]["config.js"].rstrip("\n").replace("\r\n", "\n")
            assert cm_name == "metasfresh-ui-config-" + hashlib.sha256(canonical_config.encode()).hexdigest()[:32]
            assert cm["data"] == obj(baseline["test"], "ConfigMap", "metasfresh-frontend-config")["data"]
            expected_ingress = copy.deepcopy(obj(baseline["test"], "Ingress", "metasfresh-ingress"))
            if phase != "prepare":
                expected_ingress["spec"]["rules"][0]["http"]["paths"][2]["backend"]["service"]["name"] = "metasfresh-ui-active"
            assert obj(current, "Ingress", "metasfresh-ingress") == expected_ingress
            for name in ("metasfresh-ui-active", "metasfresh-ui-preview"):
                svc = obj(current, "Service", name)
                assert svc["spec"]["selector"] == {"app": "metasfresh-ui-bluegreen"}
                assert svc["spec"]["ports"] == obj(baseline["test"], "Service", "metasfresh-ui")["spec"]["ports"]
            assert roll["spec"]["selector"]["matchLabels"] == {"app": "metasfresh-ui-bluegreen"}
            assert obj(current, "NetworkPolicy", "erp-ingress-to-ui-bluegreen")["spec"]["podSelector"]["matchLabels"] == {"app": "metasfresh-ui-bluegreen"}
            preview = obj(current, "Ingress", "metasfresh-ui-preview")
            assert preview["spec"]["rules"][0]["http"]["paths"][:2] == expected_ingress["spec"]["rules"][0]["http"]["paths"][:2]
            assert preview["spec"]["rules"][0]["http"]["paths"][2]["backend"]["service"]["name"] == "metasfresh-ui-preview"
            assert preview["spec"]["tls"][0]["secretName"] == "erp-test-preview-tls"
            for key, resource in baseline["test"].items():
                if key[0] == "Ingress":
                    continue
                if phase == "steady" and key[2] in {"metasfresh-ui", "metasfresh-frontend-config"}:
                    assert key not in current
                else:
                    assert current[key] == resource, f"baseline resource changed: {phase} {key}"
            report.append(f"PASS {phase}: CRD schema, pod spec parity, selectors, traffic, backend/PVC/Secret references/policies unchanged ({len(current)} resources)")
        assert not errors(baseline["test"], phases["prepare"])
        assert not errors(phases["prepare"], phases["cutover"])
        assert not errors(phases["cutover"], phases["steady"])
        assert not errors(phases["cutover"], phases["prepare"])
        assert errors(baseline["test"], phases["steady"]), "skipped migration accepted"
        assert errors(phases["steady"], phases["cutover"]), "retired legacy restored implicitly"
        mutation = copy.deepcopy(phases["steady"])
        obj(mutation, "Deployment", "metasfresh-api")["spec"]["replicas"] = 2
        assert errors(phases["steady"], mutation)
        overlay = temp / "extra.yaml"
        overlay.write_text(yaml.safe_dump({"ui": {"blueGreen": {"configHistory": [
            {"apiUrl": "/previous-api", "websocketUrl": "/previous-stomp"},
            {"apiUrl": "/rest/api", "websocketUrl": "/stomp"}]}}}), encoding="utf-8")
        history = objects(render(ROOT, phase="steady", extra=overlay))
        configs = [o for k, o in history.items() if k[0] == "ConfigMap" and k[2].startswith("metasfresh-ui-config-")]
        assert len(configs) == 2 and all(c["immutable"] for c in configs)
        assert not errors(phases["steady"], history)
        assert errors(history, phases["steady"]), "history pruning accepted"
        # A saved old RS can mount this still-desired immutable ConfigMap by name.
        old_name = next(c["metadata"]["name"] for c in configs if "/previous-api" in c["data"]["config.js"])
        assert obj(history, "ConfigMap", old_name)["data"]["config.js"].count("/previous-api") == 1
        bad_rollout = copy.deepcopy(obj(phases["steady"], "Rollout", "metasfresh-ui-bluegreen"))
        bad_rollout["spec"]["strategy"]["blueGreen"]["autoPromotionSecondz"] = 1
        assert list(validator.iter_errors(bad_rollout)), "unknown CRD field accepted"
        negatives = [
            {"ui": {"blueGreen": {"phase": "canary"}}},
            {"ui": {"blueGreen": {"autoPromotionEnabled": True}}},
            {"ui": {"blueGreen": {"scaleDownDelaySeconds": 0}}},
            {"ui": {"blueGreen": {"revisionHistoryLimit": 1}}},
            {"ui": {"blueGreen": {"preview": {"host": ""}}}},
            {"ui": {"blueGreen": {"preview": {"host": "erp-test.lab.internal"}}}},
            {"ui": {"blueGreen": {"preview": {"tlsSecretName": ""}}}},
            {"ui": {"blueGreen": {"migrationBaseline": {"image": "other"}}}},
            {"ui": {"image": {"digest": ""}}},
            {"ui": {"image": {"digest": "sha256:" + "0" * 64}}},
            {"ui": {"config": {"apiUrl": "https://other/rest/api"}}},
            {"ui": {"autoscaling": {"enabled": True}}},
            {"ui": {"disruptionBudget": {"enabled": True}}},
            {"ingress": {"enabled": False}},
            {"networkPolicy": {"enabled": False}},
        ]
        for values in negatives:
            overlay.write_text(yaml.safe_dump(values), encoding="utf-8")
            render(ROOT, phase=values.get("ui", {}).get("blueGreen", {}).get("phase", "prepare"), extra=overlay, lint=False, success=False)
        overlay.write_text(yaml.safe_dump({"ui": {"image": {"digest": "sha256:" + "1" * 64}}}), encoding="utf-8")
        release = objects(render(ROOT, phase="steady", extra=overlay))
        assert not errors(phases["steady"], release)
        # UI-only image release alters exactly the Rollout object.
        assert [k for k in release if release[k] != phases["steady"].get(k)] == [("Rollout", "erp", "metasfresh-ui-bluegreen")]
        overlay.write_text(yaml.safe_dump({"ui": {"blueGreen": {"scaleDownDelaySeconds": 900,
            "revisionHistoryLimit": 7, "preview": {"host": "preview-alt.lab.internal", "tlsSecretName": "preview-alt-tls"}}}}), encoding="utf-8")
        custom = objects(render(ROOT, phase="prepare", extra=overlay))
        custom_rollout = obj(custom, "Rollout", "metasfresh-ui-bluegreen")
        validator.validate(custom_rollout)
        assert custom_rollout["spec"]["strategy"]["blueGreen"]["scaleDownDelaySeconds"] == 900
        assert custom_rollout["spec"]["revisionHistoryLimit"] == 7
        custom_ingress = obj(custom, "Ingress", "metasfresh-ui-preview")["spec"]
        assert custom_ingress["rules"][0]["host"] == "preview-alt.lab.internal"
        assert custom_ingress["tls"][0] == {"hosts": ["preview-alt.lab.internal"], "secretName": "preview-alt-tls"}
        assert obj(custom, "Ingress", "metasfresh-ingress") == obj(phases["prepare"], "Ingress", "metasfresh-ingress")
        invariants = []
        for key, resource in baseline["test"].items():
            if key[0] == "Ingress" or key[2] in {"metasfresh-ui", "metasfresh-frontend-config"}:
                continue
            digest = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            invariants.append({"resource": "/".join(key), "baseline_sha256": digest(resource),
                "phase_sha256": {phase: digest(items[key]) for phase, items in phases.items()}})
        (output / "invariance.json").write_text(json.dumps(invariants, indent=2) + "\n", encoding="utf-8")
        report.append("PASS configurable delay/history/preview hostname and TLS; stable config hash; 14 unchanged resources fingerprinted")
        report.append(f"PASS release guard/config retention/CRD negative test; {len(negatives)} invalid configurations rejected")
        fragment = yaml.safe_load((ROOT / "docs/bluegreen/erp-test-application-fragment.yaml").read_text())
        assert set(fragment) == {"spec"}
        ignores = fragment["spec"]["ignoreDifferences"]
        assert {i["name"] for i in ignores} == {"metasfresh-ui-active", "metasfresh-ui-preview"}
        assert all(i == {"group": "", "kind": "Service", "name": i["name"], "namespace": "erp", "jsonPointers": ["/spec/selector/rollouts-pod-template-hash"]} for i in ignores)
        assert fragment["spec"]["syncPolicy"]["syncOptions"] == ["RespectIgnoreDifferences=true"]
        if args.previous:
            previous = temp / "previous"
            snapshot(args.previous, previous)
            before = render(previous)
            after = render(ROOT)
            failures = errors(objects(before), objects(after))
            assert not failures, failures
            (output / "previous.yaml").write_text(before, encoding="utf-8")
            (output / "desired.yaml").write_text(after, encoding="utf-8")
            report.append("PASS actual PR desired manifests vs previous: UI-only guard")
        app = yaml.safe_load((ROOT / "clusters/kubernetes-test/bootstrap/argo-rollouts-application.yaml").read_text())
        assert "automated" not in app["spec"]["syncPolicy"]
        assert app["spec"]["source"]["targetRevision"] == "2.43.7"
        if args.platform_chart:
            overlay.write_text(yaml.safe_dump(app["spec"]["source"]["helm"]["valuesObject"]), encoding="utf-8")
            chart = str(args.platform_chart.resolve())
            run(["helm", "lint", chart, "--strict", "-f", str(overlay)])
            rendered = run(["helm", "template", "argo-rollouts", chart, "--namespace", "argo-rollouts", "-f", str(overlay)])
            (output / "platform.yaml").write_text(rendered, encoding="utf-8")
            resources = objects(rendered)
            deployment = resources[("Deployment", "argo-rollouts", "argo-rollouts")]
            assert deployment["spec"]["template"]["spec"]["containers"][0]["image"] == "quay.io/argoproj/argo-rollouts:v1.10.1"
            crd = resources[("CustomResourceDefinition", "", "rollouts.argoproj.io")]
            shipped_schema = next(v for v in crd["spec"]["versions"] if v["name"] == "v1alpha1")["schema"]["openAPIV3Schema"]
            assert shipped_schema == json.loads((ROOT / "tests/schemas/rollout-v1.10.1.json").read_text())
            report.append("PASS pinned platform chart lint/render; shipped CRD matches vendored schema")
    summary = "Baseline: " + args.baseline + "\n" + "\n".join(report) + "\n"
    (output / "report.txt").write_text(summary, encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
