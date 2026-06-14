# Copyright (c) 2026 Philip Cox
# SPDX-License-Identifier: Apache-2.0

"""Core loader rejection of non-regular path inputs.

``_open_buffer`` used to call ``open(path, "rb")`` directly, which blocks
forever on a FIFO with no writer. The loader now stats the path first and
rejects anything that is not a regular file, so these tests cannot hang: a FIFO
is rejected by ``os.stat`` (which returns immediately) without a writer ever
being attached.

The FIFO/symlink/device cases are skipped on platforms that lack the relevant
syscalls (e.g. Windows) so the default pytest run stays green and fast.
"""

import os
import stat

import pytest

from multihex.core import load_files

_HAS_MKFIFO = hasattr(os, "mkfifo")
_HAS_SYMLINK = hasattr(os, "symlink")


@pytest.mark.skipif(not _HAS_MKFIFO, reason="platform has no os.mkfifo")
def test_fifo_rejected(tmp_path):
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(OSError):
        load_files([str(fifo)])


def test_directory_rejected(tmp_path):
    with pytest.raises(OSError):
        load_files([str(tmp_path)])


@pytest.mark.skipif(not _HAS_SYMLINK, reason="platform has no os.symlink")
def test_symlink_to_regular_accepted(tmp_path):
    target = tmp_path / "real.bin"
    target.write_bytes(b"abcd")
    link = tmp_path / "link.bin"
    os.symlink(target, link)
    files = load_files([str(link)])
    assert files[0].size == 4
    assert files[0].byte_at(0) == ord("a")


@pytest.mark.skipif(
    not (_HAS_MKFIFO and _HAS_SYMLINK),
    reason="platform has no os.mkfifo/os.symlink",
)
def test_symlink_to_fifo_rejected(tmp_path):
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    link = tmp_path / "link"
    os.symlink(fifo, link)
    with pytest.raises(OSError):
        load_files([str(link)])


@pytest.mark.skipif(not _HAS_SYMLINK, reason="platform has no os.symlink")
def test_dangling_symlink_is_not_found(tmp_path):
    link = tmp_path / "dangling"
    os.symlink(tmp_path / "does_not_exist", link)
    # A dangling symlink resolves to nothing, so os.stat raises
    # FileNotFoundError: it must surface as the existing missing-file path, not
    # the new "unsupported input type" rejection.
    with pytest.raises(FileNotFoundError):
        load_files([str(link)])


@pytest.mark.skipif(not _HAS_MKFIFO, reason="platform has no os.mkfifo")
def test_fifo_rejection_does_not_attach_writer(tmp_path):
    # Sanity: the rejection happens purely from the stat, so the FIFO is still a
    # FIFO afterwards and nothing ever opened it for reading.
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(OSError):
        load_files([str(fifo)])
    assert stat.S_ISFIFO(os.stat(fifo).st_mode)
