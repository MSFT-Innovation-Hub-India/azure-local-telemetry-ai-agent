"""Deploy only the independent telemetry UI and its explicitly approved shared-access policy."""

import argparse
import base64
from decimal import Decimal
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys

from tools.deploy import (
    Kubectl, LABEL, NAMESPACE, OWNER, ROOT, choose_node, manifest_resources,
    metadata, owned, preserve_placement, pull_secret,
)


def baseline(pods):
    return [{
        "namespace": p["metadata"]["namespace"], "name": p["metadata"]["name"],
        "uid": p["metadata"]["uid"], "node": p["spec"].get("nodeName"),
        "restarts": {c["name"]: c["restartCount"] for c in
                     p["status"].get("containerStatuses", []) + p["status"].get("initContainerStatuses", [])},
    } for p in pods if p["status"].get("phase") not in ("Succeeded", "Failed")
       and not (p["metadata"]["namespace"] == NAMESPACE and p["metadata"].get("labels", {}).get("app") == "telemetry-web")]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--azure-config-dir")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--preserve-placement", action="store_true")
    args = parser.parse_args()
    kube = Kubectl(args.context)
    try:
        images = json.loads((ROOT / ".local" / "images.json").read_text(encoding="utf-8-sig"))
        if not re.fullmatch(re.escape(images["server"]) + r"/ssrikantan/realtime-telemetry/app@sha256:[a-f0-9]{64}", images["app_image"]):
            raise ValueError("Analysis image must be pinned in the approved application repository.")
        namespace = kube.get("namespace", NAMESPACE)
        if not namespace:
            raise RuntimeError("Deploy and verify the database/simulator foundation first.")
        owned(namespace)
        pods = kube.get("pods")["items"]
        nodes = kube.get("nodes")["items"]
        excluded = ("timescaledb", "pump-simulator", "telemetry-web")
        node = choose_node(nodes, pods, "slmnodepool", 768, Decimal(1), excluded)
        dns = kube.get("service", "kube-dns-upstream", "kube-system")["spec"]["clusterIP"]
        text = (ROOT / "deploy" / "analysis.yaml").read_text()
        for key, value in {"APP_IMAGE": images["app_image"], "WORKER_NODE": node, "DNS_IP": dns}.items():
            text = text.replace(key, value)
        resources = manifest_resources(kube.run("create", "--dry-run=client", "--validate=false", "-f", "-", "-o", "json", payload=text))
        shared = manifest_resources(kube.run(
            "create", "--dry-run=client", "--validate=false", "-f", "-", "-o", "json",
            payload=(ROOT / "deploy" / "shared-access.yaml").read_text(),
        ))
        for resource in resources + shared:
            ns = resource["metadata"]["namespace"]
            if ns != NAMESPACE and not (
                ns == "assistant-demo" and resource["kind"] == "NetworkPolicy"
                and resource["metadata"]["name"] == "allow-telemetry-sop-access"
            ):
                raise RuntimeError("Refusing a write outside the explicitly approved deployment boundary.")
            owned(kube.get(resource["kind"], resource["metadata"]["name"], ns))
            if resource["kind"] == "Deployment":
                live = kube.get("deployment", resource["metadata"]["name"], ns)
                previous = preserve_placement(live, resource, args.preserve_placement)
                if previous:
                    choose_node([n for n in nodes if n["metadata"]["name"] == previous], pods, "slmnodepool", 768, Decimal(1), excluded)
        for kind, name in (("Secret", "telemetry-agent-credentials"), ("ConfigMap", "telemetry-models"), ("ConfigMap", "telemetry-model-trust")):
            owned(kube.get(kind, name, NAMESPACE))
        catalog = json.loads(kube.get("configmap", "assistant-models", "assistant-demo")["data"]["models.json"])
        if {m["id"] for m in catalog["models"]} != {"qwen2-5-0-5b-cpu", "qwen2-5-14b-cpu"}:
            raise RuntimeError("Both expected model deployments must be present in the existing catalog.")
        for model in catalog["models"]:
            expected = f"https://{model['id']}.foundry-local-operator.svc.cluster.local:5000/v1/chat/completions"
            if model["url"] != expected:
                raise RuntimeError("Unexpected model URL; refusing to copy credentials.")
        ca = kube.get("configmap", "foundry-local-operator-ca-bundle", "foundry-local-operator")["data"]["ca.crt"]
        if "-----BEGIN CERTIFICATE-----" not in ca:
            raise RuntimeError("Existing model CA is invalid.")
        source = kube.get("secret", "assistant-credentials", "assistant-demo")["data"]
        credentials = kube.get("secret", "telemetry-agent-credentials", NAMESPACE)
        role_exists = kube.run(
            "exec", "-n", NAMESPACE, "timescaledb-0", "--", "psql", "-U", "postgres", "-d", "telemetry",
            "-Atqc", "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='telemetry_app')",
        )
        if role_exists == "t" and credentials is None:
            raise RuntimeError("Application database role exists without its original Secret; restore credentials instead of rotating them.")
        if credentials and not credentials.get("data", {}).get("app-password"):
            raise RuntimeError("Existing application credentials are incomplete; refusing password rotation.")
        password = base64.b64decode(credentials["data"]["app-password"]).decode() if credentials else secrets.token_urlsafe(32)
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,100}", password):
            raise RuntimeError("Application password is not in the expected generated format.")
        data = {"app-password": base64.b64encode(password.encode()).decode(), "qdrant-key": source["qdrant-key"]}
        for model in catalog["models"]:
            name = "model-key-" + model["id"]
            data[name] = source[name]
        resources = [
            {"apiVersion": "v1", "kind": "Secret", "metadata": metadata("telemetry-agent-credentials"), "type": "Opaque", "data": data},
            {"apiVersion": "v1", "kind": "ConfigMap", "metadata": metadata("telemetry-models"), "data": {"models.json": json.dumps(catalog)}},
            {"apiVersion": "v1", "kind": "ConfigMap", "metadata": metadata("telemetry-model-trust"), "data": {"ca.crt": ca}},
        ] + resources
        print("Read-only preflight passed. Existing database/simulator/model/assistant pod templates are not part of this deployment.")
        if not args.apply:
            return 0
        if not args.azure_config_dir:
            raise ValueError("--azure-config-dir is required for --apply")
        (ROOT / ".local" / "analysis-pods-before.json").write_text(json.dumps(baseline(pods), indent=2))
        registry_secret = pull_secret(images, args.azure_config_dir)
        for resource in [registry_secret] + resources[:3] + shared:
            print(kube.run("apply", "--server-side", "--field-manager=realtime-telemetry", "-f", "-", payload=resource))
        migration = "\\set app_password '" + password + "'\n" + (ROOT / "db" / "002-analysis.sql").read_text()
        kube.run("exec", "-i", "-n", NAMESPACE, "timescaledb-0", "--", "psql", "-U", "postgres", "-d", "telemetry", "-f", "-", payload=migration)
        print("Applied transactional analysis schema migration; database pod was not restarted.")
        for resource in resources[3:]:
            print(kube.run("apply", "--server-side", "--field-manager=realtime-telemetry", "-f", "-", payload=resource))
        print("Independent monitoring app deployed. Existing workload resources were not reapplied.")
        return 0
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"Analysis deployment stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
