"""Compare Helm render files for a UI-only change; accepts Deployment and Rollout.
No cluster access. Never pass Secret exports: inputs must be chart renders.
"""
import argparse
from pathlib import Path
import yaml


def objects(text):
    result = {}
    for obj in yaml.safe_load_all(text):
        if not obj:
            continue
        key = (obj["kind"], obj["metadata"].get("namespace", ""), obj["metadata"]["name"])
        if key in result:
            raise ValueError(f"duplicate resource: {key}")
        if obj["kind"] == "Secret":
            raise ValueError("Secret objects are not permitted in this UI-only render")
        result[key] = obj
    return result


def ui_owned(key):
    kind, _, name = key
    return name.startswith(("metasfresh-ui", "metasfresh-frontend-config")) or name == "erp-ingress-to-ui-bluegreen"


def phase(objs):
    names = {(k[0], k[2]) for k in objs}
    if ("Rollout", "metasfresh-ui-bluegreen") not in names:
        return "disabled"
    if ("Deployment", "metasfresh-ui") not in names:
        return "steady"
    ingress = next(o for k, o in objs.items() if k[0] == "Ingress" and k[2] == "metasfresh-ingress")
    service = next(p["backend"]["service"]["name"] for p in ingress["spec"]["rules"][0]["http"]["paths"] if p["path"] == "/")
    return "cutover" if service == "metasfresh-ui-active" else "prepare"


def errors(before, after):
    issues = []
    allowed = {"disabled": {"disabled", "prepare"}, "prepare": {"prepare", "cutover"},
               "cutover": {"prepare", "cutover", "steady"}, "steady": {"steady"}}
    if phase(after) not in allowed[phase(before)]:
        issues.append(f"unsafe migration transition: {phase(before)} -> {phase(after)}")
    for key in before.keys() | after.keys():
        if ui_owned(key):
            continue
        left, right = before.get(key), after.get(key)
        if key[0] == "Ingress" and key[2] == "metasfresh-ingress" and left and right:
            # Ignore ONLY the UI root backend; REST/STOMP/TLS/annotations remain protected.
            import copy
            left, right = copy.deepcopy(left), copy.deepcopy(right)
            for obj in (left, right):
                for rule in obj["spec"]["rules"]:
                    for path in rule["http"]["paths"]:
                        if path["path"] == "/":
                            path["backend"]["service"]["name"] = "UI"
        if left != right:
            issues.append(f"non-UI resource changed: {key}")
    for key, obj in before.items():
        if key[0] == "ConfigMap" and key[2].startswith("metasfresh-ui-config-"):
            if after.get(key) != obj:
                issues.append(f"rollback config removed/changed: {key[2]}")
    if phase(after) in {"prepare", "cutover"}:
        for kind, name in [("Deployment", "metasfresh-ui"), ("Service", "metasfresh-ui"),
                           ("ConfigMap", "metasfresh-frontend-config")]:
            key = (kind, "erp", name)
            if before.get(key) != after.get(key):
                issues.append(f"legacy must remain frozen during migration: {name}")
    return issues


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args()
    failures = errors(objects(args.before.read_text(encoding="utf-8-sig")), objects(args.after.read_text(encoding="utf-8-sig")))
    if failures:
        raise SystemExit("\n".join(failures))
    print("PASS: UI-only scope, migration transition and rollback config retention")
