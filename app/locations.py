import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def algeria_locations():
    path = Path(__file__).parent / "static" / "dz_locations.json"
    return json.loads(path.read_text(encoding="utf-8"))


def wilaya_code(value):
    return str(value or "").zfill(2)
