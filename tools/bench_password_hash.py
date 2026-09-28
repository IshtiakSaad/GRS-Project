"""Measure password-hash cost on the machine that will serve logins.

Run inside the API image, with the CPU limit the api-auth service gets:

    docker compose run --rm --no-deps --cpus 1 api python tools/bench_password_hash.py

The result sets the Argon2 parameters (config/settings/base.py) and the api-auth worker count.
"""

import hashlib
import statistics
import time

from argon2 import PasswordHasher

ROUNDS = 20
PASSWORD = "correct horse battery staple"  # noqa: S105 - benchmark input


def timed(fn) -> tuple[float, float]:
    fn()  # warm-up
    samples = []
    for _ in range(ROUNDS):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples), max(samples)


def main() -> None:
    candidates = {
        # OWASP Password Storage Cheat Sheet: the two lowest recommended Argon2id settings
        "argon2id m=19MiB t=2 p=1 (OWASP min)": PasswordHasher(2, 19 * 1024, 1),
        "argon2id m=46MiB t=1 p=1 (OWASP alt)": PasswordHasher(1, 46 * 1024, 1),
        "argon2id m=64MiB t=3 p=1": PasswordHasher(3, 64 * 1024, 1),
        "argon2id m=100MiB t=2 p=8 (Django default)": PasswordHasher(2, 100 * 1024, 8),
    }
    print(f"{'hasher':<44} {'median ms':>10} {'max ms':>8} {'logins/s/core':>14}")
    for name, hasher in candidates.items():
        encoded = hasher.hash(PASSWORD)
        median, worst = timed(lambda h=hasher, e=encoded: h.verify(e, PASSWORD))
        print(f"{name:<44} {median:>10.1f} {worst:>8.1f} {1000 / median:>14.1f}")

    median, worst = timed(
        lambda: hashlib.pbkdf2_hmac("sha256", PASSWORD.encode(), b"saltsalt", 1_000_000)
    )
    name = "pbkdf2-sha256 1,000,000 (Django 5.2 default)"
    print(f"{name:<44} {median:>10.1f} {worst:>8.1f} {1000 / median:>14.1f}")


if __name__ == "__main__":
    main()
