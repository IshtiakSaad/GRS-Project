"""How many reading and typing mistakes each check-digit scheme catches, on tracking numbers.

Runs the error classes of Verhoeff's 1969 study of how people get digits wrong against a
seeded sample of tracking-number bodies (two-digit year + seven-digit serial), and counts, for
every scheme, how many corrupted numbers would still pass the check and so open someone
else's request. Damm is the scheme in apps/service_requests/tracking.py.

    docker run --rm -v "$PWD:/w" -w /w python:3.12-slim python tools/bench_check_digit.py

Standard library only. The Damm table is imported from tracking.py, so the two cannot drift.
The randomness only picks sample numbers, seeded so every run gives the same table.
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from apps.service_requests.tracking import _DAMM as DAMM  # noqa: E402

SAMPLE = 5000
SEED = 2026


def damm_ok(digits: str) -> bool:
    interim = 0
    for ch in digits:
        interim = DAMM[interim][int(ch)]
    return interim == 0


def damm_digit(body: str) -> str:
    interim = 0
    for ch in body:
        interim = DAMM[interim][int(ch)]
    return str(interim)


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def luhn_digit(body: str) -> str:
    for c in "0123456789":
        if luhn_ok(body + c):
            return c
    raise AssertionError


def mod10_ok(digits: str) -> bool:
    """The naive scheme: the check digit makes the digit sum a multiple of 10."""
    return sum(map(int, digits)) % 10 == 0


def mod10_digit(body: str) -> str:
    return str(-sum(map(int, body)) % 10)


# Verhoeff's scheme: the dihedral group D5 with a position permutation.
_V_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_V_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def verhoeff_ok(digits: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _V_D[c][_V_P[i % 8][int(ch)]]
    return c == 0


def verhoeff_digit(body: str) -> str:
    for c in "0123456789":
        if verhoeff_ok(body + c):
            return c
    raise AssertionError


SCHEMES = {
    "Damm (used)": (damm_digit, damm_ok),
    "Verhoeff": (verhoeff_digit, verhoeff_ok),
    "Luhn (bank cards)": (luhn_digit, luhn_ok),
    "Digit sum mod 10": (mod10_digit, mod10_ok),
}


# --- Verhoeff's error classes -----------------------------------------------------------------


def singles(n: str):
    for i, a in enumerate(n):
        for b in "0123456789":
            if b != a:
                yield n[:i] + b + n[i + 1 :]


def adjacent_swaps(n: str):
    for i in range(len(n) - 1):
        if n[i] != n[i + 1]:
            yield n[:i] + n[i + 1] + n[i] + n[i + 2 :]


def jump_swaps(n: str):
    for i in range(len(n) - 2):
        if n[i] != n[i + 2]:
            yield n[:i] + n[i + 2] + n[i + 1] + n[i] + n[i + 3 :]


def twins(n: str):
    for i in range(len(n) - 1):
        if n[i] == n[i + 1]:
            for b in "0123456789":
                if b != n[i]:
                    yield n[:i] + b + b + n[i + 2 :]


def jump_twins(n: str):
    for i in range(len(n) - 2):
        if n[i] == n[i + 2]:
            for b in "0123456789":
                if b != n[i]:
                    yield n[:i] + b + n[i + 1] + b + n[i + 3 :]


def phonetic(n: str):
    """English "thirteen" heard as "thirty": 1a <-> a0, for a in 2..9."""
    for i in range(len(n) - 1):
        a, b = n[i], n[i + 1]
        if a == "1" and b in "23456789":
            yield n[:i] + b + "0" + n[i + 2 :]
        elif b == "0" and a in "23456789":
            yield n[:i] + "1" + a + n[i + 2 :]


def random_other(n: str, rng: random.Random):
    """Any other number of the same length: the floor for every single-digit scheme."""
    for _ in range(20):
        other = "".join(rng.choice("0123456789") for _ in n)
        if other != n:
            yield other


CLASSES = {
    "single digit wrong": singles,
    "adjacent swap (12 -> 21)": adjacent_swaps,
    "jump swap (123 -> 321)": jump_swaps,
    "twin (11 -> 22)": twins,
    "jump twin (121 -> 323)": jump_twins,
    "phonetic (13 -> 30)": phonetic,
}


def main() -> None:
    rng = random.Random(SEED)  # noqa: S311 - sampling, not secrets
    bodies = [f"26{rng.randrange(10**7):07d}" for _ in range(SAMPLE)]
    print(f"{SAMPLE:,} tracking-number bodies (year 26, random serial), seed {SEED}\n")
    header = f"{'error class':<28}{'cases*':>10}" + "".join(f"{s:>20}" for s in SCHEMES)
    print(header + "\n" + "-" * len(header))
    for label, make in [*CLASSES.items(), ("random other number", None)]:
        # Each scheme gets its own check digit, so its own set of corrupted numbers.
        missed = dict.fromkeys(SCHEMES, 0)
        cases = dict.fromkeys(SCHEMES, 0)
        for body in bodies:
            for scheme, (digit, ok) in SCHEMES.items():
                full = body + digit(body)
                errors = make(full) if make else random_other(full, random.Random(body))  # noqa: S311
                for bad in errors:
                    cases[scheme] += 1
                    missed[scheme] += ok(bad)
        row = f"{label:<28}{cases['Damm (used)']:>10,}"
        for scheme in SCHEMES:
            row += f"{100 * (1 - missed[scheme] / cases[scheme]):>19.2f}%"
        print(row)
    print("\nEach cell: share of corrupted numbers the scheme refuses (higher is better).")
    print("*cases for Damm; the others differ slightly, since each has its own check digit.")


if __name__ == "__main__":
    main()
