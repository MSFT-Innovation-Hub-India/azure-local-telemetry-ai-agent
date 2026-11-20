"""Read-only preflight by default. Writes are confined to telemetry-demo."""

import argparse
import base64
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = "telemetry-demo"
OWNER = "realtime-telemetry"
LABEL = "app.kubernetes.io/part-of"
MIB = 1024 ** 2


def quantity(value):
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([numkKMGTPE]i?)?", str(value))
    if not match:
        raise ValueError(f"Unsupported Kubernetes quantity: {value}")
    number, suffix = match.groups()
    factors = {
        None: Decimal(1), "n": Decimal("1e-9"), "u": Decimal("1e-6"), "m": Decimal("0.001"),
        "K": Decimal(1000),
        **{s: Decimal(1000) ** i for i, s in enumerate("kMGTPE", 1)},
        **{s + "i": Decimal(1024) ** i for i, s in enumerate("KMGTPE", 1)},
    }
    return Decimal(number) * factors[suffix]


def request(pod, resource):
    spec = pod["spec"]
    regular = sum(
        (quantity(c.get("resources", {}).get("requests", {}).get(resource, "0"))
         for c in spec.get("containers", [])), Decimal(0),
    )
    sidecars = peak = Decimal(0)
    for container in spec.get("initContainers", []):
        amount = quantity(container.get("resources", {}).get("requests", {}).get(resource, "0"))
        if container.get("restartPolicy") == "Always":
            sidecars += amount
            peak = max(peak, sidecars)
        else:
            peak = max(peak, sidecars + amount)
    return max(regular + sidecars, peak) + quantity(spec.get("overhead", {}).get(resource, "0"))


class Kubectl:
    def __init__(self, context):
        self.context = context

    def run(self, *args, payload=None):
        result = subprocess.run(
            ["kubectl", "--context", self.context, "--request-timeout=30s", *args],
            input=payload if isinstance(payload, str) else json.dumps(payload) if payload else None,
            text=True, capture_output=True, timeout=90,
        )
        if result.returncode:
            # Raw API diagnostics can contain submitted Secret values.
            raise RuntimeError(f"kubectl {args[0]} failed (exit {result.returncode}); check RBAC, context and events.")
        return result.stdout.strip()

    def get(self, kind, name=None, namespace=None):
        args = ["get", kind]
        if name:
            args.extend([name, "--ignore-not-found"])
        if namespace:
            args.extend(["-n", namespace])
        elif kind == "pods":
            args.append("-A")
        output = self.run(*args, "-o", "json")
        return json.loads(output) if output else None


def owned(resource):
    if resource and resource["metadata"].get("labels", {}).get(LABEL) != OWNER:
        raise RuntimeError(f"Refusing to overwrite unowned {resource['kind']}/{resource['metadata']['name']}")


def choose_node(nodes, pods, pool, extra_memory_mib=0, extra_cpu=Decimal(0),
                excluded_apps=("timescaledb", "pump-simulator")):
    candidates = []
    for node in nodes:
        name = node["metadata"]["name"]
        if node["metadata"]["labels"].get("kubernetes.azure.com/agentpool") != pool:
            continue
        conditions = {c["type"]: c["status"] for c in node["status"]["conditions"]}
        if node["spec"].get("unschedulable") or any(
            t["effect"] in ("NoSchedule", "NoExecute") for t in node["spec"].get("taints", [])
        ) or conditions.get("Ready") != "True" or any(
            conditions.get(key) == "True" for key in ("MemoryPressure", "DiskPressure", "PIDPressure")
        ):
            continue
        existing = [
            p for p in pods if p["spec"].get("nodeName") == name
            and p["status"].get("phase") not in ("Succeeded", "Failed")
            and not (
                p["metadata"].get("namespace") == NAMESPACE
                and p["metadata"].get("labels", {}).get(LABEL) == OWNER
                and p["metadata"].get("labels", {}).get("app") in excluded_apps
            )
        ]
        memory = quantity(node["status"]["allocatable"]["memory"]) - sum(
            (request(p, "memory") for p in existing), Decimal(0),
        )
        cpu = quantity(node["status"]["allocatable"]["cpu"]) - sum(
            (request(p, "cpu") for p in existing), Decimal(0),
        )
        print(f"{name}: {memory / MIB:.0f} MiB and {cpu:.3f} CPU unreserved (not measured usage)")
        # Both pod limits, plus headroom; do not make room by altering existing workloads.
        if memory >= (2048 + 128 + 2048 + extra_memory_mib) * MIB and cpu >= Decimal("2.25") + extra_cpu:
            candidates.append((memory, name))
    if not candidates:
        raise RuntimeError("No safe Ready worker in the requested pool. Existing workloads will not be changed.")
    return max(candidates)[1]


def metadata(name):
    return {"name": name, "namespace": NAMESPACE, "labels": {LABEL: OWNER}}


def manifest_resources(output):
    resources = []
    decoder = json.JSONDecoder()
    remaining = output.lstrip()
    while remaining:
        resource, end = decoder.raw_decode(remaining)
        if not isinstance(resource, dict):
            raise ValueError("kubectl returned an invalid manifest object.")
        resources.extend(resource["items"] if resource.get("kind") == "List" else [resource])
        remaining = remaining[end:].lstrip()
    if not resources:
        raise ValueError("kubectl returned no manifest resources.")
    return resources


def preserve_placement(live, desired, enabled):
    if not live:
        return None
    if not enabled:
        raise RuntimeError("Existing telemetry workloads require --preserve-placement for redeployment.")
    previous_spec = live["spec"]["template"]["spec"]
    desired_spec = desired["spec"]["template"]["spec"]
    hostname = previous_spec.get("nodeSelector", {}).get("kubernetes.io/hostname")
    if not hostname:
        raise RuntimeError("Existing telemetry workload has no pinned node; explicit migration is required.")
    for field in ("containers", "initContainers"):
        old = {container["name"]: container.get("resources", {}) for container in previous_spec.get(field, [])}
        new = {container["name"]: container.get("resources", {}) for container in desired_spec.get(field, [])}
        if old != new:
            raise RuntimeError("--preserve-placement refuses CPU/memory request or limit changes.")
    desired_spec["nodeSelector"]["kubernetes.io/hostname"] = hostname
    return hostname


def pull_secret(images, config_dir):
    env = dict(os.environ, AZURE_CONFIG_DIR=str(Path(config_dir).resolve()))
    result = subprocess.run(
        ["az", "acr", "login", "--name", images["registry"], "--expose-token", "-o", "json"],
        text=True, capture_output=True, timeout=120, env=env, shell=os.name == "nt",
    )
    if result.returncode:
        raise RuntimeError("Cannot obtain pull credentials using the isolated approved ACR sign-in.")
    token = json.loads(result.stdout)
    if token["loginServer"] != images["server"] or not token.get("accessToken"):
        raise RuntimeError("ACR returned an unexpected login server or an empty token.")
    auth = base64.b64encode(
        ("00000000-0000-0000-0000-000000000000:" + token["accessToken"]).encode(),
    ).decode()
    config = json.dumps({"auths": {images["server"]: {"auth": auth}}})
    return {
        "apiVersion": "v1", "kind": "Secret", "metadata": metadata("telemetry-image-pull"),
        "type": "kubernetes.io/dockerconfigjson",
        "data": {".dockerconfigjson": base64.b64encode(config.encode()).decode()},
    }


def prepare(args, kube):
    images = json.loads(Path(args.images).read_text(encoding="utf-8-sig"))
    for key in ("database_image", "simulator_image"):
        if not re.fullmatch(re.escape(images["server"]) + r"/ssrikantan/realtime-telemetry/[a-z]+@sha256:[a-f0-9]{64}", images[key]):
            raise ValueError("Images must be approved-registry realtime-telemetry repositories pinned by digest.")
    owned(kube.get("namespace", NAMESPACE))
    nodes = kube.get("nodes")["items"]
    pods = kube.get("pods")["items"]
    node = choose_node(nodes, pods, args.nodepool)
    storage = kube.get("storageclass", args.storage_class)
    if not storage or storage["provisioner"] != "azlocal.csi.azure.com":
        raise RuntimeError("Expected the existing Azure Local CSI storage class; no storage settings were changed.")
    dns = kube.get("service", "kube-dns-upstream", "kube-system")
    if not dns or not dns["spec"].get("clusterIP"):
        raise RuntimeError("Existing upstream CoreDNS service is required; shared DNS will not be changed.")
    text = (ROOT / "deploy" / "stack.yaml").read_text()
    for placeholder, value in {
        "DATABASE_IMAGE": images["database_image"], "SIMULATOR_IMAGE": images["simulator_image"],
        "WORKER_NODE": node, "STORAGE_CLASS": args.storage_class, "DNS_IP": dns["spec"]["clusterIP"],
    }.items():
        text = text.replace(placeholder, value)
    resources = manifest_resources(
        kube.run("create", "--dry-run=client", "--validate=false", "-f", "-", "-o", "json", payload=text),
    )
    resources.append({
        "apiVersion": "v1", "kind": "ConfigMap", "metadata": metadata("telemetry-schema"),
        "data": {"001-schema.sql": (ROOT / "db" / "001-schema.sql").read_text()},
    })
    for resource in resources:
        name = resource["metadata"]["name"]
        if resource["kind"] == "Namespace":
            if name != NAMESPACE:
                raise RuntimeError("Manifest attempts to change an unexpected namespace.")
        elif resource["metadata"].get("namespace") != NAMESPACE:
            raise RuntimeError("Manifest attempts a write outside telemetry-demo.")
        owned(kube.get(resource["kind"], name, None if resource["kind"] == "Namespace" else NAMESPACE))
    for name in ("telemetry-database", "telemetry-image-pull"):
        owned(kube.get("secret", name, NAMESPACE))
    for resource in resources:
        if resource["kind"] not in ("StatefulSet", "Deployment"):
            continue
        live = kube.get(resource["kind"], resource["metadata"]["name"], NAMESPACE)
        hostname = preserve_placement(live, resource, args.preserve_placement or args.refresh_pull_only)
        if hostname:
            choose_node([n for n in nodes if n["metadata"]["name"] == hostname], pods, args.nodepool)
    return images, resources, pods


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--nodepool", default="slmnodepool")
    parser.add_argument("--storage-class", default="default")
    parser.add_argument("--images", default=str(ROOT / ".local" / "images.json"))
    parser.add_argument("--azure-config-dir")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--preserve-placement", action="store_true", help="Required for upgrades: keep existing nodes and reject resource changes.")
    parser.add_argument("--refresh-pull-only", action="store_true")
    args = parser.parse_args()
    kube = Kubectl(args.context)
    try:
        images, resources, pods = prepare(args, kube)
        if not args.apply:
            print("Preflight passed. Read-only mode: no resources changed.")
            return 0
        if not args.azure_config_dir:
            raise ValueError("--azure-config-dir is required with --apply")
        registry_secret = pull_secret(images, args.azure_config_dir)
        if args.refresh_pull_only:
            if not kube.get("namespace", NAMESPACE):
                raise RuntimeError("Cannot refresh pull credentials before the initial deployment.")
            print(kube.run("apply", "--server-side", "--field-manager=realtime-telemetry", "-f", "-", payload=registry_secret))
            return 0
        database_secret = kube.get("secret", "telemetry-database", NAMESPACE)
        if database_secret:
            if not all(database_secret.get("data", {}).get(key) for key in ("admin-password", "writer-password", "reader-password")):
                raise RuntimeError("Existing database credentials are incomplete; refusing silent rotation.")
        else:
            if kube.get("persistentvolumeclaim", "timescaledb-data", NAMESPACE):
                raise RuntimeError("Existing data PVC without credentials; restore the original Secret instead of rotating passwords.")
            database_secret = {
                "apiVersion": "v1", "kind": "Secret", "metadata": metadata("telemetry-database"),
                "type": "Opaque",
                "data": {
                    key: base64.b64encode(secrets.token_urlsafe(32).encode()).decode()
                    for key in ("admin-password", "writer-password", "reader-password")
                },
            }
        local = ROOT / ".local"
        local.mkdir(exist_ok=True)
        baseline_path = local / "existing-pods-before.json"
        if not baseline_path.exists():
            baseline_path.write_text(json.dumps([
                {
                    "namespace": p["metadata"]["namespace"], "name": p["metadata"]["name"],
                    "uid": p["metadata"]["uid"],
                    "restarts": {c["name"]: c["restartCount"] for c in p["status"].get("containerStatuses", []) + p["status"].get("initContainerStatuses", [])},
                }
                for p in pods if p["metadata"]["namespace"] != NAMESPACE
                and p["status"].get("phase") not in ("Succeeded", "Failed")
            ], indent=2))
        namespace = next(r for r in resources if r["kind"] == "Namespace")
        print(kube.run("apply", "--server-side", "--field-manager=realtime-telemetry", "-f", "-", payload=namespace))
        ordered = [registry_secret, database_secret] + sorted(
            [r for r in resources if r["kind"] != "Namespace"],
            key=lambda r: r["kind"] in ("StatefulSet", "Deployment"),
        )
        for resource in ordered:
            print(kube.run("apply", "--server-side", "--field-manager=realtime-telemetry", "-f", "-", payload=resource))
        print("Applied only telemetry-demo resources. Verify schema, live writes and existing workload health.")
        return 0
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"Deployment stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
