import random
import time
from pathlib import Path
from typing import Callable, Optional, Tuple


def interruptible_sleep(
    total_seconds: float,
    should_stop: Callable[[], bool],
    step_seconds: float = 0.2,
) -> bool:
    """Sleep in small chunks so caller can cancel promptly."""
    deadline = time.time() + max(0.0, total_seconds)
    while time.time() < deadline:
        if should_stop():
            return False
        remaining = deadline - time.time()
        time.sleep(min(step_seconds, max(0.0, remaining)))
    return not should_stop()


def atomic_write_bytes(dest_path: Path, content: bytes) -> None:
    """Write bytes atomically to avoid partially written files."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_suffix(dest_path.suffix + ".part")
    with open(temp_path, "wb") as f:
        f.write(content)
    temp_path.replace(dest_path)


def download_bytes_with_retry(
    get_once: Callable[[], Tuple[int, bytes]],
    should_stop: Callable[[], bool],
    attempts: int = 3,
    base_delay: float = 1.0,
    max_jitter: float = 0.4,
) -> Optional[bytes]:
    """
    Retry a byte download function with exponential backoff.
    `get_once` returns (status_code, bytes) and may raise.
    """
    last_error = None
    for attempt in range(1, attempts + 1):
        if should_stop():
            return None
        try:
            status, body = get_once()
            if status == 200 and body:
                return body
            last_error = RuntimeError(f"HTTP {status}")
        except Exception as exc:
            last_error = exc

        if attempt < attempts:
            delay = (base_delay * (2 ** (attempt - 1))) + random.uniform(0.0, max_jitter)
            if not interruptible_sleep(delay, should_stop):
                return None

    if last_error:
        raise last_error
    return None
