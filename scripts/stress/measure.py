#!/usr/bin/env python3
# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Run a command under resource supervision for the multihex stress suite.

This is the safety mechanism the shell stress scripts rely on. It spawns a
command in its own process group, polls the child's peak resident-set size
(VmHWM from procfs), and enforces a wall-clock timeout and an optional RSS
ceiling -- killing the whole group if either is exceeded. That containment is
what makes the hostile probes safe to run on a workstation: an unbounded-memory
defect can never OOM the host, and a hang (e.g. a FIFO with no writer) can never
leak a blocked process.

Stdlib only.

Usage:
    measure.py --timeout SECS [--rss-cap-kb N] [--out FILE] [--err FILE]
               [--sigint-after SECS] -- CMD ARG...

Output (one machine-parseable line on stdout):
    rc=<int> secs=<float> peak_kb=<int> timed_out=<0|1> rss_exceeded=<0|1>

``rc`` is the child's exit status; a process killed by signal N reports
``rc=-N`` (Python's Popen convention), which the shell maps to 128+N.

Exit codes of measure.py itself:
    0   measurement completed (inspect the rc= field for the child's status)
    2   usage error
    77  cannot measure on this platform (no procfs) -- shell maps to SKIP
"""

import argparse
import os
import signal
import subprocess
import sys
import time

POLL_SECONDS = 0.02
NO_PROCFS_EXIT = 77


def _read_vmhwm_kb(pid: int) -> int:
    """Return VmHWM (peak RSS) in kB for ``pid``, or 0 if unavailable.

    A fast-exiting child makes /proc/<pid>/status vanish; callers treat a
    transient 0 as "no new sample" and keep the last good watermark.
    """
    try:
        with open(f"/proc/{pid}/status", "r") as fh:
            for line in fh:
                if line.startswith("VmHWM:"):
                    # "VmHWM:   123456 kB"
                    return int(line.split()[1])
    except (FileNotFoundError, ProcessLookupError, ValueError, IndexError):
        return 0
    return 0


def _procfs_available() -> bool:
    try:
        with open(f"/proc/{os.getpid()}/status", "r") as fh:
            return any(line.startswith("VmHWM:") for line in fh)
    except OSError:
        return False


def _kill_group(pid: int, sig: int) -> None:
    try:
        os.killpg(os.getpgid(pid), sig)
    except (ProcessLookupError, PermissionError):
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="measure.py", add_help=True)
    parser.add_argument("--timeout", type=float, required=True,
                        help="wall-clock seconds before the child group is SIGKILLed")
    parser.add_argument("--rss-cap-kb", type=int, default=None,
                        help="kill the child if peak RSS exceeds this many kB")
    parser.add_argument("--out", default=None, help="redirect child stdout to this path")
    parser.add_argument("--err", default=None, help="redirect child stderr to this path")
    parser.add_argument("--sigint-after", type=float, default=None,
                        help="send SIGINT to the child group this many seconds in")
    parser.add_argument("cmd", nargs=argparse.REMAINDER,
                        help="-- followed by the command to run")
    args = parser.parse_args(argv)

    cmd = args.cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        parser.error("no command given (use: measure.py ... -- CMD ARG...)")

    if not _procfs_available():
        print("SKIP reason=no-procfs", file=sys.stderr)
        return NO_PROCFS_EXIT

    out_fh = open(args.out, "wb") if args.out else None
    err_fh = open(args.err, "wb") if args.err else None
    try:
        start = time.monotonic()
        proc = subprocess.Popen(
            cmd,
            stdout=out_fh if out_fh else None,
            stderr=err_fh if err_fh else None,
            start_new_session=True,  # own process group; enables killpg containment
        )
    except OSError as exc:
        if out_fh:
            out_fh.close()
        if err_fh:
            err_fh.close()
        print("rc=127 secs=0.0 peak_kb=0 timed_out=0 rss_exceeded=0", flush=True)
        print(f"measure.py: cannot exec {cmd[0]!r}: {exc}", file=sys.stderr)
        return 0

    peak_kb = 0
    timed_out = 0
    rss_exceeded = 0
    sigint_sent = False
    try:
        while True:
            sample = _read_vmhwm_kb(proc.pid)
            if sample > peak_kb:
                peak_kb = sample
            now = time.monotonic()
            elapsed = now - start

            if (args.sigint_after is not None and not sigint_sent
                    and elapsed >= args.sigint_after):
                _kill_group(proc.pid, signal.SIGINT)
                sigint_sent = True

            if args.rss_cap_kb is not None and peak_kb > args.rss_cap_kb:
                rss_exceeded = 1
                _kill_group(proc.pid, signal.SIGKILL)
                proc.wait()
                break

            if elapsed >= args.timeout:
                timed_out = 1
                _kill_group(proc.pid, signal.SIGKILL)
                proc.wait()
                break

            if proc.poll() is not None:
                # Final watermark read before the entry disappears.
                sample = _read_vmhwm_kb(proc.pid)
                if sample > peak_kb:
                    peak_kb = sample
                break

            time.sleep(POLL_SECONDS)
    finally:
        # Guarantee the whole group is gone so nothing leaks.
        _kill_group(proc.pid, signal.SIGKILL)
        if proc.poll() is None:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if out_fh:
            out_fh.close()
        if err_fh:
            err_fh.close()

    secs = time.monotonic() - start
    rc = proc.returncode if proc.returncode is not None else -signal.SIGKILL
    print(
        f"rc={rc} secs={secs:.3f} peak_kb={peak_kb} "
        f"timed_out={timed_out} rss_exceeded={rss_exceeded}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
