import hashlib
from typing import Optional


def deterministic_chunk_id(
    source_id: str,
    source_type: str,
    page: Optional[int] = None,
    slide: Optional[int] = None,
    start_sec: Optional[float] = None,
    end_sec: Optional[float] = None,
    extra: str = "",
) -> str:
    """Stable id for a chunk so updates overwrite instead of duplicating.

    Mixes source coordinates into a sha1 to keep it short but stable.
    """
    key = f"src={source_id}|type={source_type}|page={page}|slide={slide}|start={start_sec}|end={end_sec}|{extra}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()
