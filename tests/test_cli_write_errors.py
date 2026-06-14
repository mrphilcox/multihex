# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Regression coverage for stdout write failures and interrupts in the CLI.

Broken-pipe behavior is covered separately in test_cli_broken_pipe.py; this
file covers the non-EPIPE write OSError path (e.g. ENOSPC on a full device) and
the Ctrl-C path, both of which previously leaked Python tracebacks.
"""

import errno
import io
import os
import subprocess
import sys

import pytest

from multihex import cli


class _FullStdout:
    """Fake stdout whose writes/flushes/close all fail like a full device.

    close() failing too exercises the broadened guard in cli._silence_stdout,
    which must swallow the final flush so shutdown stays quiet.
    """

    def write(self, _text):
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    def flush(self):
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    def close(self):
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))


def test_write_oserror_reports_and_exits_nonzero(monkeypatch):
    """A non-EPIPE stdout OSError yields a stderr diagnostic and exit code 1."""
    fake_err = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdout", _FullStdout())
    monkeypatch.setattr(cli.sys, "stderr", fake_err)

    with pytest.raises(SystemExit) as exc_info:
        cli.write_stdout_chunk("anything")

    assert exc_info.value.code == 1
    assert "error writing output" in fake_err.getvalue()


def test_keyboard_interrupt_exits_130_quietly(monkeypatch):
    """Ctrl-C during a run exits 130 with no traceback and clean stderr."""
    fake_err = io.StringIO()
    monkeypatch.setattr(cli.sys, "stderr", fake_err)

    def _interrupt(_argv=None):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_run", _interrupt)

    assert cli.main([]) == 130
    assert fake_err.getvalue() == ""


@pytest.mark.skipif(
    not (os.path.exists("/dev/full") and os.environ.get("MULTIHEX_DEV_FULL_TEST")),
    reason="opt-in: set MULTIHEX_DEV_FULL_TEST=1 on Linux with /dev/full",
)
def test_dev_full_end_to_end(tmp_path):
    """End-to-end ENOSPC against the real /dev/full: clean diagnostic, no trace."""
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(bytes(range(256)) * 8)
    b.write_bytes(bytes((x ^ 0x55) for x in range(256)) * 8)

    with open("/dev/full", "w") as full:
        proc = subprocess.run(
            [sys.executable, "-m", "multihex.cli", a.name, b.name],
            cwd=tmp_path,
            stdout=full,
            stderr=subprocess.PIPE,
            text=True,
        )

    assert proc.returncode == 1
    assert "error writing output" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert "Exception ignored" not in proc.stderr
