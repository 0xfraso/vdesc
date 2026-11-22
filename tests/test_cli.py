import sys

from vdesc.cli import _stale_venv_scripts


def test_stale_venv_scripts(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ok = bin_dir / "pytest"
    ok.write_text(f"#!{sys.executable}\n")
    dead = bin_dir / "vdesc"
    dead.write_text(f"#!{tmp_path / 'gone' / '.venv' / 'bin' / 'python'}\n")
    (bin_dir / "activate").write_text("# no shebang, ignored\n")
    assert _stale_venv_scripts(bin_dir) == [dead]
    assert _stale_venv_scripts(tmp_path / "missing") == []
