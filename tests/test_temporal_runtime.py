from pathlib import Path
from fred_os.provenance import Authority
from fred_os.runtime.kernel import RuntimeKernel


def prepare(root: Path) -> None:
    (root / "config").mkdir()
    (root / "config" / "systemos_base.toml").write_text('''[meta]
schema_version = "2.0"
revision = "test"
tenant_id = "test"
project_id = "fred-os"

[governance]
pass_floor = 0.75
review_floor = 0.50
block_ceiling = 0.25

[runtime]
active = true

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
''')


def test_temporal_receipt_and_source_link(tmp_path: Path):
    prepare(tmp_path)
    kernel = RuntimeKernel.boot(root_dir=tmp_path, profile="test")
    try:
        source = kernel.memory.ingest("provenance", "Provenance", "Immutable DeepLinks preserve evidence provenance.", Authority.IMPLEMENTATION)["deeplinks"][0]
        outcome = kernel.process_turn("How can immutable DeepLinks preserve evidence provenance?")
        assert source in outcome["temporal"]["linked_sources"]
        shard_id = outcome["temporal"]["shard_id"]
        assert any(item["deeplink"] == source for item in kernel.memory.sources_for_tsc_shard(shard_id))
    finally:
        kernel.close()
