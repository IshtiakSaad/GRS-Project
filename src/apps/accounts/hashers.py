from django.contrib.auth.hashers import Argon2PasswordHasher


class Argon2idHasher(Argon2PasswordHasher):
    """Argon2id at the OWASP minimum: 19 MiB, 2 passes, 1 lane.

    One lane because each gunicorn worker hashes on one core; more lanes add threads, not
    safety. Cost measured by tools/bench_password_hash.py. Raising these later is safe: Django
    rehashes a password with the new parameters the next time its owner logs in.
    """

    time_cost = 2
    memory_cost = 19 * 1024  # KiB
    parallelism = 1
