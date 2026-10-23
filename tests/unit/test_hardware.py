from universe_models.hardware import detect


def test_detect_returns_a_sane_snapshot_on_this_machine() -> None:
    hw = detect()
    assert hw.ram_bytes > 0
    assert hw.cpu_threads and hw.cpu_threads >= 1
    assert hw.os
    assert isinstance(hw.notes, list)
    for gpu in hw.gpus:
        assert gpu.name
