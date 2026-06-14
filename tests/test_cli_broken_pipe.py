"""Regression coverage for downstream pipe consumers closing stdout early."""

import os
import subprocess
import sys


def _write_large_pair(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    data = bytes((i * 7) & 0xFF for i in range(256 * 1024))
    a.write_bytes(data)
    b.write_bytes(bytes(byte ^ 0x55 for byte in data))
    return a.name, b.name


def _run_until_stdout_closed(tmp_path, args, lines_to_read=10):
    env = os.environ.copy()
    proc = subprocess.Popen(
        [sys.executable, "-m", "multihex.cli", *args],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert proc.stdout is not None
    assert proc.stderr is not None

    try:
        for _ in range(lines_to_read):
            assert proc.stdout.readline()
        proc.stdout.close()
        returncode = proc.wait(timeout=10)
        stderr = proc.stderr.read()
    except Exception:
        proc.kill()
        proc.wait()
        raise
    finally:
        proc.stderr.close()

    return returncode, stderr


def test_text_output_exits_cleanly_when_pipe_consumer_closes(tmp_path):
    a, b = _write_large_pair(tmp_path)

    returncode, stderr = _run_until_stdout_closed(tmp_path, [a, b])

    assert returncode == 0
    assert "BrokenPipeError" not in stderr
    assert "Traceback" not in stderr


def test_json_output_exits_cleanly_when_pipe_consumer_closes(tmp_path):
    a, b = _write_large_pair(tmp_path)

    returncode, stderr = _run_until_stdout_closed(tmp_path, ["--json", a, b])

    assert returncode == 0
    assert "BrokenPipeError" not in stderr
    assert "Traceback" not in stderr
