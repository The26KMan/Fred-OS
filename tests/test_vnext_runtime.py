from pathlib import Path
from fred_os.runtime.kernel import RuntimeKernel
from fred_os.provenance import Authority

ROOT=Path(__file__).resolve().parents[1]

def test_boot_and_route():
    kernel=RuntimeKernel.boot(root_dir=ROOT,profile='development')
    try:
        result=kernel.process_turn('Design a semantic memory migration with DeepLinks.')
        assert result['verdict'].decision == 'PASS'
        assert result['outputs']['S1']['task_class'] == 'systemic'
        assert 'S2' in result['outputs']
    finally:
        kernel.close()

def test_versioned_memory_returns_locator():
    kernel=RuntimeKernel.boot(root_dir=ROOT,profile='development')
    try:
        receipt=kernel.memory.ingest('test-note','Test Note','DeepLinks resolve immutable evidence fragments.',Authority.IMPLEMENTATION)
        result=kernel.memory.recall('immutable evidence')
        assert receipt['deeplinks'][0].startswith('deeplink://')
        assert result.hits[0]['deeplink'].startswith('deeplink://')
    finally:
        kernel.close()
