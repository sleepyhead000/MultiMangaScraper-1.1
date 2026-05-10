from pathlib import Path

from download_utils import atomic_write_bytes, download_bytes_with_retry, interruptible_sleep


def test_atomic_write_bytes(tmp_path: Path):
    target = tmp_path / "a" / "file.bin"
    atomic_write_bytes(target, b"hello")
    assert target.exists()
    assert target.read_bytes() == b"hello"
    assert not target.with_suffix(".bin.part").exists()


def test_interruptible_sleep_stops_early():
    calls = {"n": 0}

    def should_stop():
        calls["n"] += 1
        return calls["n"] >= 2

    ok = interruptible_sleep(2.0, should_stop, step_seconds=0.01)
    assert ok is False


def test_download_bytes_with_retry_recovers():
    attempts = {"n": 0}

    def get_once():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("transient")
        return 200, b"ok"

    body = download_bytes_with_retry(get_once, should_stop=lambda: False, attempts=3, base_delay=0.01, max_jitter=0.0)
    assert body == b"ok"
    assert attempts["n"] == 2
