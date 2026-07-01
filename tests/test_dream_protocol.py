from fred_os.protocols.dream_protocol import Component, Constraint, DreamEngine, Status


def inventory():
    components = [
        Component("runtime_kernel", "RuntimeKernel", Status.IMPLEMENTED, evidence=("boot path", "config hash"), risk=.25, unlock_value=.90),
        Component("semantic_memory", "Semantic Memory Lake", Status.IMPLEMENTED, evidence=("artifact revisions", "DeepLinks"), risk=.30, unlock_value=.88),
        Component("s1_core", "System-1 mapper", Status.IMPLEMENTED, evidence=("schema", "tests"), risk=.22, unlock_value=.80),
        Component("s1_runtime_adapter", "System-1 runtime adapter", Status.IMPLEMENTED_UNWIRED, ("s1_core",), ("branch source",), .34, .5, .82),
        Component("temporal_sphere", "Temporal Sphere", Status.IMPLEMENTED_UNWIRED, ("s1_runtime_adapter",), ("branch source",), .36, .5, .88),
        Component("memory_tsc_contract", "Memory-TSC contract", Status.DOCUMENTED, ("semantic_memory", "temporal_sphere"), ("reference architecture",), .42, .5, .92),
        Component("system2", "System-2 association", Status.DOCUMENTED, ("s1_runtime_adapter", "temporal_sphere"), ("spec", "migration guide"), .45, .5, .85),
        Component("system6", "System-6 influence", Status.TESTED_PROTOTYPE, ("system2",), ("prototype",), .42, .5, .72),
        Component("system3", "System-3 NLP", Status.CANDIDATE, evidence=("spec",), risk=.55, unlock_value=.65),
        Component("system4", "System-4 QTE", Status.CANDIDATE, evidence=("spec",), risk=.65, unlock_value=.60),
        Component("system5", "System-5 ethical", Status.CANDIDATE, evidence=("spec",), risk=.48, unlock_value=.60),
        Component("system7", "System-7 metacognition", Status.DOCUMENTED, ("s1_runtime_adapter", "system2", "temporal_sphere"), ("spec",), .52, .5, .78),
        Component("test_harness", "Integration tests", Status.IMPLEMENTED_UNWIRED, evidence=("local tests",), risk=.30, unlock_value=.86),
    ]
    constraints = [
        Constraint("kernel_tsc_unwired", "critical", "TSC is not passed into RuntimeKernel turns.", ("runtime_kernel", "temporal_sphere")),
        Constraint("s1_adapter_unwired", "critical", "Registry uses the prior S1 plugin.", ("runtime_kernel", "s1_runtime_adapter")),
        Constraint("tsc_memory_bidirectional_missing", "critical", "TSC and Memory Lake references are not reciprocal.", ("temporal_sphere", "semantic_memory")),
    ]
    return components, constraints


def test_recommends_integration_first():
    components, constraints = inventory()
    review = DreamEngine().review(components, constraints)
    assert review["recommended_path"]["id"] == "integration_first"
    assert review["recommended_path"]["blocked_by"] == []
    assert review["recommended_path"]["order"] == ["wire_s1_runtime", "wire_tsc_kernel", "restore_tsc_memory_contract", "integration_tests", "complete_s2"]


def test_rejects_premature_breadth_and_association_paths():
    components, constraints = inventory()
    review = DreamEngine().review(components, constraints)
    rejected = {item["path"]: item["reason"] for item in review["rejection_log"]}
    assert "kernel_tsc_unwired" in rejected["vertical_slice_s1_s2"]
    assert "s1_adapter_unwired" in rejected["breadth_first"]


def test_inventory_digest_is_deterministic():
    components, constraints = inventory()
    first = DreamEngine().review(components, constraints)
    second = DreamEngine().review(components, constraints)
    assert first["inventory_digest"] == second["inventory_digest"]
