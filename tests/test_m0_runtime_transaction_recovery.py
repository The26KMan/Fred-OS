from pathlib import Path

from fred_os.provenance import Authority
from fred_os.runtime.contracts import CommandEnvelope
from fred_os.runtime.kernel import RuntimeKernel
from fred_os.runtime.state import StateCapsule


def prepare(root: Path) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "systemos_base.toml").write_text(
        '''[meta]
schema_version = "2.0"
revision = "m0-test"
tenant_id = "test"
project_id = "fred-os"

[governance]
pass_floor = 0.75
review_floor = 0.50
block_ceiling = 0.25

[runtime]
active = true
state_store_path = "data/runtime_state.jsonl"
journal_path = "data/runtime.wal.jsonl"

[protocol]
default_mode = "CHAINING"
allow_genius_escalation = true

[memory]
repository_path = "data/memory.sqlite3"
working_limit = 7

[temporal]
working_capacity = 3
micro_window = 2
meso_window = 2
episodic_min_reinforcement = 2
projection_limit = 3

[observability]
event_log_path = "data/events.jsonl"

[systems]
enabled = ["S1", "S2", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12", "S13"]
''',
        encoding="utf-8",
    )


def command() -> CommandEnvelope:
    return CommandEnvelope(
        command_id="cmd_001",
        target_capability="s1.cognitive_map",
        payload={"input": "Design a semantic memory migration with immutable DeepLinks."},
        session_id="session_test_01",
        idempotency_key="ik_001",
        timestamp=1.0,
    )


def seed_memory(kernel: RuntimeKernel) -> str:
    return kernel.memory.ingest(
        "m0-source",
        "M0 Source",
        "Immutable DeepLinks preserve semantic memory provenance during migration.",
        Authority.IMPLEMENTATION,
    )["deeplinks"][0]


def test_m0_runtime_transaction_recovery(tmp_path: Path):
    root = tmp_path / "primary"
    prepare(root)
    state_path = root / "data" / "runtime_state.jsonl"
    journal_path = root / "data" / "runtime.wal.jsonl"

    # 1. BOOT + GENESIS + CAPABILITY DISCOVERY
    kernel = RuntimeKernel.boot(
        root_dir=root,
        profile="test",
        state_store_path=state_path,
        journal_path=journal_path,
        session_id="session_test_01",
    )
    assert kernel.status == "READY"
    capsule_0 = kernel.get_current_capsule()
    assert capsule_0.sequence == 0
    assert capsule_0.session_id == "session_test_01"
    assert {item["name"] for item in kernel.list_capabilities()} >= {"runtime.process_turn", "s1.cognitive_map"}

    source = seed_memory(kernel)

    # 2-6. COMMAND -> EXECUTION -> RECEIPTS -> DELTA -> CAPSULE -> TX_COMMIT
    result = kernel.dispatch(command())
    assert result.status == "SUCCESS"
    assert result.delta is not None
    assert result.delta.prev_capsule_id == capsule_0.capsule_id
    assert result.delta.next_capsule_id == result.state_capsule_id

    receipt_components = [receipt.component for receipt in result.receipts]
    assert receipt_components[0:4] == ["Governance", "S1", "MemoryLake", "Router"]
    assert "S2" in receipt_components
    assert "TSC" in receipt_components
    assert [receipt.sequence for receipt in result.receipts] == list(range(1, len(result.receipts) + 1))
    for previous, current in zip(result.receipts, result.receipts[1:]):
        assert current.parent_receipt_id == previous.receipt_id
    assert all(receipt.status == "OK" for receipt in result.receipts)

    capsule_1 = kernel.get_current_capsule()
    assert capsule_1.capsule_id == result.state_capsule_id
    assert capsule_1.sequence == 1
    assert capsule_1.temporal_state["current_turn"] == 1
    assert kernel.temporal.current_turn == 1
    assert kernel.temporal.session_id == "session_test_01"
    assert result.outputs["temporal"]["source_deeplinks"] == [source]
    assert result.outputs["temporal"]["linked_sources"] == [source]

    latest_commit = kernel.journal.latest_commit()
    assert latest_commit is not None
    assert latest_commit.entry_type == "TX_COMMIT"
    assert latest_commit.payload["capsule_id"] == capsule_1.capsule_id
    assert latest_commit.payload["receipt_hashes"] == [receipt.compute_hash() for receipt in result.receipts]

    # 7-10. SHUTDOWN -> REBOOT -> HYDRATE -> LOGICAL EQUIVALENCE
    before_restart = capsule_1.to_normalized_dict(exclude_keys=["created_at", "host_metadata"])
    kernel.shutdown()

    rebooted = RuntimeKernel.boot(
        root_dir=root,
        profile="test",
        state_store_path=state_path,
        journal_path=journal_path,
        session_id="session_test_01",
    )
    restored = rebooted.get_current_capsule()
    after_restart = restored.to_normalized_dict(exclude_keys=["created_at", "host_metadata"])
    assert after_restart == before_restart
    assert restored.logical_state_hash == capsule_1.logical_state_hash
    assert rebooted.temporal.current_turn == 1
    assert rebooted.temporal.session_id == "session_test_01"
    shard_id = result.outputs["temporal"]["shard_id"]
    assert any(item["deeplink"] == source for item in rebooted.memory.sources_for_tsc_shard(shard_id))

    # 11. CRASH RECOVERY: an uncommitted candidate must never become authoritative.
    rebooted.journal.append_entry(
        "TX_START",
        {
            "command_id": "cmd_uncommitted",
            "idempotency_key": "ik_uncommitted",
            "target_capability": "s1.cognitive_map",
            "before_capsule_id": restored.capsule_id,
        },
    )
    uncommitted_candidate = StateCapsule.next(
        previous=restored,
        command_id="cmd_uncommitted",
        temporal_state=restored.temporal_state,
        memory_state=restored.memory_state,
        repository_state=restored.repository_state,
        receipt_hashes=(),
    )
    rebooted.state_store.append(uncommitted_candidate)
    rebooted.shutdown()

    post_crash = RuntimeKernel.boot(
        root_dir=root,
        profile="test",
        state_store_path=state_path,
        journal_path=journal_path,
        session_id="session_test_01",
    )
    assert post_crash.get_current_capsule().capsule_id == capsule_1.capsule_id
    interrupted = post_crash.reconcile_wal()
    assert any(item["command_id"] == "cmd_uncommitted" for item in interrupted)
    assert uncommitted_candidate.capsule_id not in post_crash.journal.committed_capsule_ids()
    post_crash.shutdown()

    # 12. DETERMINISTIC LOGICAL REPLAY from a clean genesis with the same fixed inputs.
    replay_root = tmp_path / "replay"
    prepare(replay_root)
    replay = RuntimeKernel.boot(root_dir=replay_root, profile="test", session_id="session_test_01")
    replay_source = seed_memory(replay)
    assert replay_source == source
    replay_result = replay.dispatch(command())
    replay_capsule = replay.get_current_capsule()

    assert [receipt.compute_hash() for receipt in replay_result.receipts] == [
        receipt.compute_hash() for receipt in result.receipts
    ]
    assert replay_capsule.logical_state_hash == capsule_1.logical_state_hash
    assert replay_capsule.capsule_id == capsule_1.capsule_id
    replay.shutdown()
