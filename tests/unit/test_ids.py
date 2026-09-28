import time

from apps.common.ids import uuid7


def test_uuid7_version_and_variant():
    value = uuid7()
    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_uuid7_embeds_current_time():
    before = time.time_ns() // 1_000_000
    value = uuid7()
    after = time.time_ns() // 1_000_000
    assert before <= value.int >> 80 <= after


def test_uuid7_orders_by_creation_time():
    first = uuid7()
    time.sleep(0.002)
    second = uuid7()
    assert first < second  # new ids append to the index instead of landing at random
