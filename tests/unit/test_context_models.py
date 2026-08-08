from artcode.config import ContextConfig
from artcode.context_management.models import CompressionCircuit


def test_context_thresholds_use_integer_floor() -> None:
    config = ContextConfig(1_000_000)

    assert config.automatic_threshold == 835_000
    assert config.forced_threshold == 885_000


def test_compression_circuit_reset_clears_all_state() -> None:
    circuit = CompressionCircuit(3, True, True)

    circuit.reset()

    assert circuit.consecutive_failures == 0
    assert circuit.open is False
    assert circuit.forced_attempted is False
