import time
import uuid

from universe_common.ids import uuid7


def test_uuid7_version_variant_and_time() -> None:
    value = uuid.UUID(uuid7())
    assert value.version == 7
    assert value.variant == uuid.RFC_4122
    ms = value.int >> 80
    assert abs(ms - time.time() * 1000) < 5_000


def test_uuid7_is_strictly_increasing_within_a_process() -> None:
    ids = [uuid7() for _ in range(20_000)]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)
