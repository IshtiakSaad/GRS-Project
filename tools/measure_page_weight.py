"""What a phone downloads to open each page of the web app for the first time.

Reads the static export (web/out, from `npm run build` in web/), and for every page adds up the
HTML and every script and stylesheet it references, gzipped at level 9 as the image serves
them (gzip_static). Then the time to fetch that much at a few connection speeds. Transfer
only: it ignores round trips, TLS setup and the phone's time to run the scripts, so real
first loads are slower; later pages reuse the cached scripts.

    cd web && npm run build && cd .. && python tools/measure_page_weight.py
"""

import gzip
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "web" / "out"
ASSET = re.compile(r"""(?:src|href)="(/_next/static/[^"]+\.(?:js|css))\"""")

# Effective downstream throughput, in kilobits per second. Labels, not measurements: the
# 2G/EDGE figure is a typical sustained rate, and the rest are common test profiles.
SPEEDS = {"2G (EDGE) 100 kbps": 100, "slow 3G 400 kbps": 400, "4G 9 Mbps": 9000}


def gz(path: Path) -> int:
    return len(gzip.compress(path.read_bytes(), compresslevel=9))


def main() -> None:
    rows = []
    shared: set[str] | None = None
    for html in sorted(OUT.rglob("index.html")):
        route = "/" + str(html.parent.relative_to(OUT)).replace("\\", "/").strip(".")
        assets = set(ASSET.findall(html.read_text(encoding="utf-8")))
        shared = assets if shared is None else shared & assets
        size = gz(html) + sum(gz(OUT / a.lstrip("/")) for a in assets)
        rows.append((route.rstrip("/") or "/", len(assets), size))

    print(f"{'page':<22}{'files':>6}{'gzip KB':>9}" + "".join(f"{s:>20}" for s in SPEEDS))
    for route, files, size in rows:
        times = "".join(f"{size * 8 / 1000 / kbps:>19.1f}s" for kbps in SPEEDS.values())
        print(f"{route:<22}{files:>6}{size / 1024:>9.1f}{times}")
    common = sum(gz(OUT / a.lstrip("/")) for a in shared or ())
    sizes = sorted(s / 1024 for _, _, s in rows)
    median, largest = sizes[len(sizes) // 2], sizes[-1]
    print(f"\n{len(rows)} pages; median {median:.1f} KB, largest {largest:.1f} KB")
    print(f"shared by every page (cached after the first): {common / 1024:.1f} KB")


if __name__ == "__main__":
    main()
