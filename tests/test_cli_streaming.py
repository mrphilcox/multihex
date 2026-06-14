"""CLI text dump streaming behavior."""

from multihex import cli


class RecordingStdout:
    def __init__(self):
        self.writes = []

    def write(self, text):
        self.writes.append(text)
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return False


def test_text_dump_writes_each_rendered_row_incrementally(tmp_path, monkeypatch):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"abcd")
    b.write_bytes(b"abXd")

    stdout = RecordingStdout()
    monkeypatch.setattr(cli.sys, "stdout", stdout)

    cli.main(["--width", "1", str(a), str(b)])

    row_blocks = [text for text in stdout.writes if text.startswith("0x")]
    assert len(row_blocks) == 4
    assert all(block.endswith("\n") for block in row_blocks)
    assert all(
        sum(line.startswith("0x") for line in block.splitlines()) == 1
        for block in row_blocks
    )
