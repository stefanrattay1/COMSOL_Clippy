from __future__ import annotations

from comsol_clippy.pdf import list_sources


def test_list_sources_ignores_unsupported_files_and_directories(tmp_path):
    (tmp_path / "HeatTransferModuleUsersGuide.PDF").write_text("pdf")
    (tmp_path / "notes.MD").write_text("md")
    (tmp_path / "draft.docx").write_text("docx")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "inside.pdf").write_text("nested")

    assert list_sources(tmp_path) == ["HeatTransferModuleUsersGuide.PDF", "notes.MD"]