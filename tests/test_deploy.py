import copy
import unittest

from tools.deploy import LABEL, OWNER, choose_node, manifest_resources, owned, preserve_placement, request


class DeploymentGuardTests(unittest.TestCase):
    def node(self):
        return {
            "metadata": {"name": "new-worker", "labels": {"kubernetes.azure.com/agentpool": "slmnodepool"}},
            "spec": {},
            "status": {
                "conditions": [{"type": "Ready", "status": "True"}],
                "allocatable": {"cpu": "8", "memory": "16Gi"},
            },
        }

    def test_refuses_foreign_resources(self):
        resource = {"kind": "Secret", "metadata": {"name": "existing"}}
        with self.assertRaises(RuntimeError):
            owned(resource)
        resource["metadata"]["labels"] = {LABEL: OWNER}
        owned(resource)

    def test_native_sidecar_and_init_peak_count_toward_capacity(self):
        pod = {"spec": {
            "containers": [{"resources": {"requests": {"memory": "1Gi"}}}],
            "initContainers": [
                {"restartPolicy": "Always", "resources": {"requests": {"memory": "256Mi"}}},
                {"resources": {"requests": {"memory": "2Gi"}}},
            ],
            "overhead": {"memory": "64Mi"},
        }}
        self.assertEqual(request(pod, "memory"), (2048 + 256 + 64) * 1024 ** 2)

    def test_refuses_tainted_pressured_or_wrong_pool_nodes(self):
        node = self.node()
        self.assertEqual(choose_node([node], [], "slmnodepool"), "new-worker")
        for mutation in ("taint", "pressure", "pool"):
            candidate = copy.deepcopy(node)
            if mutation == "taint":
                candidate["spec"]["taints"] = [{"effect": "NoSchedule"}]
            elif mutation == "pressure":
                candidate["status"]["conditions"].append({"type": "MemoryPressure", "status": "True"})
            else:
                candidate["metadata"]["labels"]["kubernetes.azure.com/agentpool"] = "other"
            with self.assertRaises(RuntimeError):
                choose_node([candidate], [], "slmnodepool")

    def test_counts_existing_workloads_and_requires_headroom(self):
        pod = {
            "metadata": {"namespace": "foundry-local-operator"},
            "spec": {"nodeName": "new-worker", "containers": [
                {"resources": {"requests": {"cpu": "6", "memory": "13Gi"}}},
            ]},
            "status": {"phase": "Running"},
        }
        with self.assertRaises(RuntimeError):
            choose_node([self.node()], [pod], "slmnodepool")

    def test_reads_concatenated_kubectl_manifest_objects(self):
        output = '{"kind":"Namespace","metadata":{"name":"telemetry-demo"}}\n'
        output += '{"kind":"List","items":[{"kind":"Deployment"}]}\n'
        self.assertEqual([r["kind"] for r in manifest_resources(output)], ["Namespace", "Deployment"])
        with self.assertRaises(ValueError):
            manifest_resources("")

    def test_preserves_current_node_instead_of_new_capacity_winner(self):
        live = {"spec": {"template": {"spec": {
            "nodeSelector": {"kubernetes.io/hostname": "original-worker"},
            "containers": [{"name": "database", "resources": {
                "requests": {"cpu": "500m", "memory": "1Gi"},
                "limits": {"cpu": "1", "memory": "2Gi"},
            }}],
        }}}}
        desired = copy.deepcopy(live)
        desired["spec"]["template"]["spec"]["nodeSelector"]["kubernetes.io/hostname"] = "larger-new-worker"
        with self.assertRaises(RuntimeError):
            preserve_placement(live, desired, False)
        self.assertEqual(preserve_placement(live, desired, True), "original-worker")
        self.assertEqual(desired["spec"]["template"]["spec"]["nodeSelector"]["kubernetes.io/hostname"], "original-worker")
        for field in ("requests", "limits"):
            changed = copy.deepcopy(desired)
            changed["spec"]["template"]["spec"]["containers"][0]["resources"][field]["memory"] = "3Gi"
            with self.assertRaises(RuntimeError):
                preserve_placement(live, changed, True)


if __name__ == "__main__":
    unittest.main()
