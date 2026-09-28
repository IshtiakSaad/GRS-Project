import threading

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db


def _scalar(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()[0]


@pytest.mark.parametrize(
    ("utc_moment", "year"),
    [
        ("2026-12-31 17:59:59+00", 2026),  # 23:59:59 in Dhaka
        ("2026-12-31 18:00:00+00", 2027),  # midnight in Dhaka: new year, though UTC is not
    ],
)
def test_tracking_year_follows_dhaka_time(utc_moment, year):
    assert _scalar("SELECT tracking_year(%s::timestamptz)", [utc_moment]) == year


def test_serials_increase_within_a_year():
    first = _scalar("SELECT next_tracking_serial(2026)")
    second = _scalar("SELECT next_tracking_serial(2026)")
    assert second == first + 1


def test_missing_year_is_created_on_demand():
    assert _scalar("SELECT to_regclass('tracking_seq_2092')") is None
    assert _scalar("SELECT next_tracking_serial(2092)") == 1


def test_absurd_years_are_refused():
    with pytest.raises(Exception, match="out of range"):
        _scalar("SELECT next_tracking_serial(1066)")


@pytest.mark.concurrency
def test_parallel_first_submissions_of_a_new_year_both_succeed(connect_as):
    """Two submissions race to create the year's sequence; both get distinct numbers."""
    year = 2093
    barrier = threading.Barrier(2)
    results, errors = [], []

    def submit():
        try:
            with connect_as() as conn:
                barrier.wait()
                results.append(
                    conn.execute("SELECT next_tracking_serial(%s)", [year]).fetchone()[0]
                )
        except Exception as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert errors == []
    assert sorted(results) == [1, 2]
