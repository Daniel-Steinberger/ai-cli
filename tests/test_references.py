"""`@path` references: detection, reading, limits, and the attached context block."""

from rich.console import Console

from ai_cli import references


def test_finds_file_and_reads_content(tmp_path):
    (tmp_path / "hello.py").write_text("print('hi')\n")
    refs = references.find("was macht @hello.py?", cwd=tmp_path)
    assert len(refs) == 1
    assert refs[0].kind == "file"
    assert refs[0].usable
    assert "print('hi')" in refs[0].body


def test_trailing_punctuation_is_not_part_of_the_path(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    for text in ["@a.txt?", "@a.txt.", "erklär @a.txt, bitte", "(@a.txt)"]:
        refs = references.find(text, cwd=tmp_path)
        assert [r.kind for r in refs] == ["file"], text
        assert refs[0].raw == "a.txt"


def test_directory_is_listed(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "one.txt").write_text("1")
    (tmp_path / "sub" / "inner").mkdir()
    refs = references.find("@sub", cwd=tmp_path)
    assert refs[0].kind == "dir"
    # Directories first, marked with a trailing slash.
    assert refs[0].body.splitlines() == ["inner/", "one.txt"]
    assert "2 entries" in refs[0].note


def test_quoted_path_with_spaces(tmp_path):
    (tmp_path / "my file.txt").write_text("content")
    refs = references.find('lies @"my file.txt" vor', cwd=tmp_path)
    assert refs[0].kind == "file"
    assert refs[0].body == "content"


def test_email_and_unknown_paths_are_reported_not_attached(tmp_path):
    refs = references.find("schreib an daniel@dvs.ag über @nichtda.txt", cwd=tmp_path)
    # The email's "@dvs.ag" is not at a token start, so it is not a reference at all.
    assert [r.raw for r in refs] == ["nichtda.txt"]
    assert refs[0].kind == "missing"
    assert not refs[0].usable
    assert references.context_block(refs, tmp_path) == ""


def test_at_inside_a_word_is_ignored(tmp_path):
    (tmp_path / "x.txt").write_text("x")
    assert references.find("foo@x.txt", cwd=tmp_path) == []


def test_home_relative_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "notes.md").write_text("note")
    refs = references.find("@~/notes.md", cwd=tmp_path / "elsewhere")
    assert refs[0].kind == "file"
    assert refs[0].body == "note"


def test_duplicates_collapse(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    refs = references.find("@a.txt und @a.txt und @./a.txt", cwd=tmp_path)
    assert len(refs) == 1


def test_binary_file_is_not_included(tmp_path):
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02binary")
    refs = references.find("@blob.bin", cwd=tmp_path)
    assert refs[0].kind == "binary"
    assert refs[0].body == ""
    assert "not included" in refs[0].note


def test_large_file_is_truncated(tmp_path):
    (tmp_path / "big.log").write_text("a" * (references.MAX_BYTES + 5000))
    refs = references.find("@big.log", cwd=tmp_path)
    assert refs[0].kind == "file"
    assert len(refs[0].body) < references.MAX_BYTES + 200
    assert "truncated" in refs[0].note
    assert "truncated" in refs[0].body


def test_too_many_references_are_reported_as_skipped(tmp_path):
    names = []
    for i in range(references.MAX_FILES + 3):
        (tmp_path / f"f{i}.txt").write_text(str(i))
        names.append(f"@f{i}.txt")
    refs = references.find(" ".join(names), cwd=tmp_path)
    assert sum(r.usable for r in refs) == references.MAX_FILES
    skipped = [r for r in refs if r.kind == "skipped"]
    assert len(skipped) == 3
    assert "more than" in skipped[0].note


def test_context_block_labels_files_and_dirs(tmp_path):
    (tmp_path / "a.txt").write_text("inhalt")
    (tmp_path / "d").mkdir()
    block = references.context_block(references.find("@a.txt @d", cwd=tmp_path), tmp_path)
    assert "File `a.txt`" in block
    assert "Directory `d`" in block
    assert "inhalt" in block


def test_expand_appends_context_and_reports(tmp_path, capsys):
    (tmp_path / "a.txt").write_text("inhalt")
    console = Console(force_terminal=False)
    out_text = references.expand("erklär @a.txt und @weg.txt", console, cwd=tmp_path)
    assert out_text.startswith("erklär @a.txt und @weg.txt")
    assert "inhalt" in out_text
    printed = capsys.readouterr().out
    assert "attached" in printed and "a.txt" in printed
    assert "not attached" in printed and "weg.txt" in printed


def test_expand_without_references_is_unchanged(tmp_path):
    assert references.expand("nur text", None, cwd=tmp_path) == "nur text"
