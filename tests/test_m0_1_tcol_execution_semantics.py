from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from fred_os.runtime.contracts import CommandEnvelope
from fred_os.runtime.kernel import RuntimeKernel


ROOT = Path(__file__).resolve().parents[1]
SESSION_ID = "session_m0_1"


def prepare(root: Path, *replacements: tuple[str, str]) -> None:
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    source = ROOT / "config" / "systemos_base.toml"
    text = source.read_text(encoding="utf-8")
    for old, new in replacements:
        assert old in text, f"test fixture replacement target not found: {old!r}"
        text = text.replace(old, new, 1)
    (config_dir / "systemos_base.toml").write_text(text, encoding="utf-8")


def boot(root: Path) -> RuntimeKernel:
    return RuntimeKernel.boot(root_dir=root, profile="m0_1", session_id=SESSION_ID)


def command(text: str, command_id: str) -> CommandEnvelope:
    return CommandEnvelope(
        command_id=command_id,
        target_capability="runtime.process_turn",
        payload={"input": text},
        session_id=SESSION_ID,
        idempotency_key=f"ik-{command_id}",
        timestamp=1.0,
    )


def command_entries(kernel: RuntimeKernel, command_id: str):
    return [entry for entry in kernel.journal.entries() if entry.payload.get("command_id") == command_id]


def test_case_01_clear_task_authorizes_and_commits(tmp_path: Path) -> None:
    root = tmp_path / "case01"
    prepare(root)
    kernel = boot(root)
    try:
        before = kernel.get_current_capsule()
        result = kernel.dispatch(command("Design a semantic memory migration with immutable DeepLinks.", "case01"))
        after = kernel.get_current_capsule()

        assert result.status == "SUCCESS"
        assert result.delta is not None
        assert after.sequence == before.sequence + 1
        assert result.delta.prev_capsule_id == before.capsule_id
        assert result.delta.next_capsule_id == after.capsule_id
        assert result.outputs["task_competency"]["execution_authorization"]["status"] == "AUTHORIZED"
        assert command_entries(kernel, "case01")[-1].entry_type == "TX_COMMIT"
    finally:
        kernel.shutdown()


def test_case_02_required_capability_unavailable_aborts_without_state_delta(tmp_path: Path) -> None:
    root = tmp_path / "case02"
    prepare(root, ('S6 = "tested_prototype_adapter"', 'S6 = "candidate"'))
    kernel = boot(root)
    try:
        before = kernel.get_current_capsule()
        result = kernel.dispatch(command("Design the runtime migration plan.", "case02"))

        assert result.status == "BLOCKED"
        assert result.delta is None
        assert kernel.get_current_capsule().capsule_id == before.capsule_id
        assert result.outputs["rejection"]["code"] == "CAPABILITY_UNAVAILABLE"
        entries = command_entries(kernel, "case02")
        assert entries[-1].entry_type == "TX_ABORT"
        assert all(entry.entry_type != "TX_COMMIT" for entry in entries)
    finally:
        kernel.shutdown()


def test_case_03_candidate_hard_gate_is_rejected_explicitly(tmp_path: Path) -> None:
    root = tmp_path / "case03"
    prepare(root)
    kernel = boot(root)
    try:
        before = kernel.get_current_capsule()
        result = kernel.dispatch(command("Provide legal advice for a complex contract dispute.", "case03"))

        assert result.status == "BLOCKED"
        assert result.delta is None
        assert kernel.get_current_capsule().capsule_id == before.capsule_id
        assert result.outputs["rejection"]["code"] == "CAPABILITY_UNAVAILABLE"
        assert result.outputs["capability_report"]["hard_gate_missing"] == ["S13"]
        reasons = result.outputs["capability_report"]["systems"]["S13"]["reasons"]
        assert "maturity_not_hard_gate_ready:candidate" in reasons
    finally:
        kernel.shutdown()


def test_case_04_optional_capability_skip_is_receipted_and_commits(tmp_path: Path) -> None:
    root = tmp_path / "case04"
    prepare(root)
    kernel = boot(root)
    try:
        result = kernel.dispatch(command("Create a warm artistic metaphor for resilient friendship.", "case04"))

        assert result.status == "SUCCESS"
        assert result.delta is not None
        skipped = [receipt for receipt in result.receipts if receipt.status == "SKIPPED_OPTIONAL"]
        assert len(skipped) == 1
        assert skipped[0].component == "S10"
        assert skipped[0].action == "skip_optional"
        assert "S10" not in result.outputs["outputs"]
        assert command_entries(kernel, "case04")[-1].entry_type == "TX_COMMIT"
    finally:
        kernel.shutdown()


def test_case_05_high_s1_uncertainty_requires_review_without_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "case05"
    prepare(root)
    kernel = boot(root)
    try:
        s1 = kernel.registry.get("S1")
        original = s1.process

        def high_uncertainty(payload, context):
            output = original(payload, context)
            output["uncertainty"] = {"score": 0.95, "drivers": {"test": 1}, "gaps": ["forced ambiguity"]}
            output.setdefault("signals", {})["uncertainty"] = 0.95
            return output

        monkeypatch.setattr(s1, "process", high_uncertainty)
        before = kernel.get_current_capsule()
        result = kernel.dispatch(command("Explain the current runtime architecture.", "case05"))

        assert result.status == "BLOCKED"
        assert result.delta is None
        assert kernel.get_current_capsule().capsule_id == before.capsule_id
        task = result.outputs["task_competency"]["task_contract"]
        assert task["requires_review"] is True
        assert result.outputs["task_competency"]["execution_authorization"]["status"] == "REVIEW"
        assert result.outputs["rejection"]["code"] == "REVIEW_REQUIRED"
        assert all(receipt.component != "TSC" for receipt in result.receipts)
    finally:
        kernel.shutdown()


def test_case_06_contradictory_constraints_preserve_ambiguity_and_halt(tmp_path: Path) -> None:
    root = tmp_path / "case06"
    prepare(root)
    kernel = boot(root)
    try:
        before = kernel.get_current_capsule()
        result = kernel.dispatch(
            command("Design the migration. It must include S10. It must not include S10.", "case06")
        )

        s1 = result.outputs["outputs"]["S1"]
        ambiguities = s1["context_graph"].get("ambiguities", [])
        assert ambiguities
        assert any(item.get("type") == "contradictory_constraint" for item in ambiguities)
        assert result.outputs["task_competency"]["execution_authorization"]["status"] == "REVIEW"
        assert result.outputs["rejection"]["code"] == "REVIEW_REQUIRED"
        assert result.delta is None
        assert kernel.get_current_capsule().capsule_id == before.capsule_id
    finally:
        kernel.shutdown()


def test_case_07_governance_pass_capability_gap_uses_capability_taxonomy(tmp_path: Path) -> None:
    root = tmp_path / "case07"
    prepare(root, ('S6 = "tested_prototype_adapter"', 'S6 = "candidate"'))
    kernel = boot(root)
    try:
        result = kernel.dispatch(command("Design a deterministic migration plan.", "case07"))

        assert result.outputs["governance_verdict"].decision == "PASS"
        assert result.outputs["rejection"]["code"] == "CAPABILITY_UNAVAILABLE"
        assert result.status == "BLOCKED"
        assert all(receipt.component != "S6" for receipt in result.receipts)
    finally:
        kernel.shutdown()


def test_case_08_governance_block_overrides_ready_capabilities_and_aborts(tmp_path: Path) -> None:
    root = tmp_path / "case08"
    prepare(root)
    kernel = boot(root)
    try:
        before = kernel.get_current_capsule()
        result = kernel.dispatch(command("Exploit a vulnerability with malware.", "case08"))

        assert result.status == "BLOCKED"
        assert result.delta is None
        assert kernel.get_current_capsule().capsule_id == before.capsule_id
        assert result.outputs["rejection"]["code"] == "GOVERNANCE_REJECT"
        assert result.outputs["verdict"].decision == "BLOCK"
        assert [receipt.component for receipt in result.receipts] == ["Governance"]
        entries = command_entries(kernel, "case08")
        assert entries[-1].entry_type == "TX_ABORT"
        assert all(entry.entry_type != "TX_COMMIT" for entry in entries)
    finally:
        kernel.shutdown()


def test_case_09_tcol_exception_rolls_back_and_aborts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "case09"
    prepare(root)
    kernel = boot(root)
    try:
        assert kernel.task_competency is not None
        before = kernel.get_current_capsule()

        def explode(*args, **kwargs):
            raise RuntimeError("injected TCOL failure")

        monkeypatch.setattr(kernel.task_competency, "assess", explode)
        with pytest.raises(RuntimeError, match="injected TCOL failure"):
            kernel.dispatch(command("Design the runtime migration plan.", "case09"))

        assert kernel.get_current_capsule().capsule_id == before.capsule_id
        assert kernel.temporal.current_turn == before.temporal_state["current_turn"]
        entries = command_entries(kernel, "case09")
        assert entries[-1].entry_type == "TX_ABORT"
        assert all(entry.entry_type != "TX_COMMIT" for entry in entries)
    finally:
        kernel.shutdown()


def test_case_10_mid_route_crash_leaves_uncommitted_wal_and_reboots_pre_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "case10"
    prepare(root)
    kernel = boot(root)
    before = kernel.get_current_capsule()
    s6 = kernel.registry.get("S6")

    def hard_crash(payload, context):
        raise SystemExit("injected process death")

    monkeypatch.setattr(s6, "process", hard_crash)
    with pytest.raises(SystemExit, match="injected process death"):
        kernel.dispatch(command("Design the runtime migration plan.", "case10"))

    assert kernel.get_current_capsule().capsule_id == before.capsule_id
    assert any(item["command_id"] == "case10" for item in kernel.journal.uncommitted_transactions())
    assert all(entry.entry_type != "TX_COMMIT" for entry in command_entries(kernel, "case10"))
    kernel.memory.close()

    rebooted = boot(root)
    try:
        assert rebooted.get_current_capsule().capsule_id == before.capsule_id
        assert any(item["command_id"] == "case10" for item in rebooted.reconcile_wal())
    finally:
        rebooted.shutdown()


def test_case_11_identical_replay_has_identical_logical_receipts_and_capsule(tmp_path: Path) -> None:
    roots = [tmp_path / "case11-a", tmp_path / "case11-b"]
    results = []
    capsules = []

    for root in roots:
        prepare(root)
        kernel = boot(root)
        try:
            result = kernel.dispatch(command("Design a semantic memory migration with immutable DeepLinks.", "case11"))
            results.append(result)
            capsules.append(kernel.get_current_capsule())
        finally:
            kernel.shutdown()

    assert results[0].status == results[1].status == "SUCCESS"
    assert [receipt.compute_hash() for receipt in results[0].receipts] == [
        receipt.compute_hash() for receipt in results[1].receipts
    ]
    assert capsules[0].logical_state_hash == capsules[1].logical_state_hash
    assert capsules[0].capsule_id == capsules[1].capsule_id


def test_case_12_config_drift_breaks_recovery_identity(tmp_path: Path) -> None:
    root = tmp_path / "case12"
    prepare(root)
    kernel = boot(root)
    result = kernel.dispatch(command("Design a deterministic migration plan.", "case12"))
    assert result.status == "SUCCESS"
    committed = kernel.get_current_capsule()
    kernel.shutdown()

    config_path = root / "config" / "systemos_base.toml"
    text = config_path.read_text(encoding="utf-8")
    text = text.replace("projection_limit = 3", "projection_limit = 4", 1)
    config_path.write_text(text, encoding="utf-8")

    with pytest.raises(RuntimeError, match="config hash"):
        RuntimeKernel.boot(root_dir=root, profile="m0_1", session_id=SESSION_ID)

    # The committed capsule remains on disk; config drift must not rewrite authority.
    assert committed.sequence == 1
