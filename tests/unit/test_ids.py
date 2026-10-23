import time
import uuid

from universe_common.ids import is_uuid, uuid7


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


def test_is_uuid_accepts_only_canonical_ids() -> None:
    assert is_uuid(uuid7()) and is_uuid(str(uuid.uuid4()))
    for bad in ("..\\secret", "../secret", "", "not-a-uuid", uuid7().upper(), uuid7() + "\n", 123, None):
        assert not is_uuid(bad), bad
