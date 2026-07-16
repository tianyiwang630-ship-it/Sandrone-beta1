import io
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi import UploadFile

from agent.server.routes import files


def test_resolve_child_rejects_parent_escape(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()

    with pytest.raises(HTTPException) as exc:
        files._resolve_child(root.resolve(), "../outside.txt")

    assert exc.value.status_code == 400


def test_read_file_rejects_large_preview(monkeypatch, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "huge.txt"
    target.write_bytes(b"x" * (files.PREVIEW_LIMIT_BYTES + 1))

    monkeypatch.setattr(
        files.state_store,
        "get_project",
        lambda project_id: {"workspace_path": str(root)} if project_id == "proj" else None,
    )

    result = files.read_file(project_id="proj", path="huge.txt")

    assert result.previewable is False
    assert result.content is None
    assert "256KB" in (result.message or "")


def test_read_file_rejects_unknown_extension(monkeypatch, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "image.bin"
    target.write_bytes(b"abc")

    monkeypatch.setattr(
        files.state_store,
        "get_project",
        lambda project_id: {"workspace_path": str(root)} if project_id == "proj" else None,
    )

    result = files.read_file(project_id="proj", path="image.bin")

    assert result.previewable is False
    assert result.content is None


def test_read_docx_preview_extracts_text_and_tables(monkeypatch, tmp_path):
    docx = pytest.importorskip("docx")
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "report.docx"
    document = docx.Document()
    document.add_paragraph("第一段内容")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "姓名"
    table.cell(0, 1).text = "张三"
    document.save(target)

    monkeypatch.setattr(
        files.state_store,
        "get_project",
        lambda project_id: {"workspace_path": str(root)} if project_id == "proj" else None,
    )

    result = files.read_file(project_id="proj", path="report.docx")

    assert result.previewable is True
    assert result.language == "markdown"
    assert "第一段内容" in (result.content or "")
    assert "| 姓名 | 张三 |" in (result.content or "")


def test_pdf_preview_uses_inline_file_even_when_large(monkeypatch, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "scan.pdf"
    target.write_bytes(b"%PDF-1.4\n" + b"x" * (files.PREVIEW_LIMIT_BYTES + 1))

    monkeypatch.setattr(
        files.state_store,
        "get_project",
        lambda project_id: {"workspace_path": str(root)} if project_id == "proj" else None,
    )

    result = files.read_file(project_id="proj", path="scan.pdf")
    response = files.raw_file(project_id="proj", path="scan.pdf")

    assert result.previewable is True
    assert result.language == "pdf"
    assert result.content is None
    assert response.media_type == "application/pdf"


def test_pptx_preview_uses_raw_file_with_unicode_name_and_uppercase_suffix(monkeypatch, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "汇报 文稿.PPTX"
    target.write_bytes(b"PK\x03\x04fake-pptx")

    monkeypatch.setattr(
        files.state_store,
        "get_project",
        lambda project_id: {"workspace_path": str(root)} if project_id == "proj" else None,
    )

    result = files.read_file(project_id="proj", path=target.name)
    response = files.raw_file(project_id="proj", path=target.name)

    assert result.previewable is True
    assert result.language == "pptx"
    assert result.content is None
    assert response.media_type == "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def test_raw_preview_rejects_non_pdf_or_pptx_file(monkeypatch, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "notes.txt"
    target.write_text("hello", encoding="utf-8")

    monkeypatch.setattr(
        files.state_store,
        "get_project",
        lambda project_id: {"workspace_path": str(root)} if project_id == "proj" else None,
    )

    with pytest.raises(HTTPException) as exc:
        files.raw_file(project_id="proj", path=target.name)

    assert exc.value.status_code == 400
    assert "PDF and PPTX" in str(exc.value.detail)


def test_html_preview_returns_source_text_for_iframe_render(monkeypatch, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "preview.html"
    target.write_text("<!doctype html><html><body><h1>Hello</h1></body></html>", encoding="utf-8")

    monkeypatch.setattr(
        files.state_store,
        "get_project",
        lambda project_id: {"workspace_path": str(root)} if project_id == "proj" else None,
    )

    result = files.read_file(project_id="proj", path="preview.html")

    assert result.previewable is True
    assert result.language == "html"
    assert "<h1>Hello</h1>" in (result.content or "")


def test_asset_route_stays_inside_workspace_and_serves_static_files(monkeypatch, tmp_path):
    root = tmp_path / "workspace"
    assets = root / "pages"
    assets.mkdir(parents=True)
    target = assets / "style.css"
    target.write_text("body { color: red; }", encoding="utf-8")

    monkeypatch.setattr(
        files.state_store,
        "get_project",
        lambda project_id: {"workspace_path": str(root)} if project_id == "proj" else None,
    )

    response = files.file_asset(project_id="proj", asset_path="pages/style.css")

    assert response.path == str(target)
    assert response.media_type == "text/css"


def test_raw_pdf_rejects_parent_escape(monkeypatch, tmp_path):
    root = tmp_path / "workspace"
    outside = tmp_path / "outside.pdf"
    root.mkdir()
    outside.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr(
        files.state_store,
        "get_project",
        lambda project_id: {"workspace_path": str(root)} if project_id == "proj" else None,
    )

    with pytest.raises(HTTPException) as exc:
        files.raw_file(project_id="proj", path="../outside.pdf")

    assert exc.value.status_code == 400


def test_asset_route_rejects_parent_escape(monkeypatch, tmp_path):
    root = tmp_path / "workspace"
    outside = tmp_path / "outside.css"
    root.mkdir()
    outside.write_text("body{}", encoding="utf-8")

    monkeypatch.setattr(
        files.state_store,
        "get_project",
        lambda project_id: {"workspace_path": str(root)} if project_id == "proj" else None,
    )

    with pytest.raises(HTTPException) as exc:
        files.file_asset(project_id="proj", asset_path="../outside.css")

    assert exc.value.status_code == 400


def test_collect_conflicts_checks_target_directory(monkeypatch, tmp_path):
    root = tmp_path / "workspace"
    target_dir = root / "docs"
    target_dir.mkdir(parents=True)
    (target_dir / "same.txt").write_text("old", encoding="utf-8")

    conflicts = files._collect_conflicts(root, "docs", ["same.txt", "new.txt"])

    assert len(conflicts) == 1
    assert conflicts[0].name == "same.txt"
    assert conflicts[0].path == "docs/same.txt"


def test_create_folder_stays_inside_workspace(monkeypatch, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setattr(
        files.state_store,
        "get_project",
        lambda project_id: {"workspace_path": str(root)} if project_id == "proj" else None,
    )

    info = files.create_folder(files.CreateFolderRequest(project_id="proj", target_path="", name="notes"))

    assert info.is_dir is True
    assert (root / "notes").is_dir()


def test_upload_file_renames_on_conflict(monkeypatch, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "report.txt").write_text("old", encoding="utf-8")
    monkeypatch.setattr(
        files.state_store,
        "get_project",
        lambda project_id: {"workspace_path": str(root)} if project_id == "proj" else None,
    )

    upload = UploadFile(filename="report.txt", file=io.BytesIO(b"new"))
    result = files.upload_file(
        file=upload,
        project_id="proj",
        target_path="",
        relative_path="report.txt",
        conflict_strategy="rename",
    )

    assert result.path == "report_(1).txt"
    assert (root / "report_(1).txt").read_text(encoding="utf-8") == "new"


def test_open_in_folder_selects_file_in_explorer(monkeypatch, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "notes" / "735px-枫丹 奇械.png"
    target.parent.mkdir()
    target.write_text("hello", encoding="utf-8")

    calls: list[list[str]] = []
    monkeypatch.setattr(
        files.state_store,
        "get_project",
        lambda project_id: {"workspace_path": str(root)} if project_id == "proj" else None,
    )
    monkeypatch.setattr(files.subprocess, "Popen", lambda args: calls.append(args))

    result = files.open_in_folder(files.OpenInFolderRequest(project_id="proj", path="notes/735px-枫丹 奇械.png"))

    assert result == {"ok": True}
    assert calls == [["explorer.exe", "/select,", str(target)]]


def test_open_in_folder_selects_directory_in_explorer(monkeypatch, tmp_path):
    root = tmp_path / "workspace"
    target = root / "素材 补充"
    target.mkdir(parents=True)

    calls: list[list[str]] = []
    monkeypatch.setattr(
        files.state_store,
        "get_project",
        lambda project_id: {"workspace_path": str(root)} if project_id == "proj" else None,
    )
    monkeypatch.setattr(files.subprocess, "Popen", lambda args: calls.append(args))

    result = files.open_in_folder(files.OpenInFolderRequest(project_id="proj", path=target.name))

    assert result == {"ok": True}
    assert calls == [["explorer.exe", "/select,", str(target)]]


def test_open_in_folder_opens_workspace_root_when_path_is_empty(monkeypatch, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()

    opened: list[str] = []
    monkeypatch.setattr(
        files.state_store,
        "get_project",
        lambda project_id: {"workspace_path": str(root)} if project_id == "proj" else None,
    )
    monkeypatch.setattr(files.os, "startfile", lambda path: opened.append(path), raising=False)

    result = files.open_in_folder(files.OpenInFolderRequest(project_id="proj", path=""))

    assert result == {"ok": True}
    assert opened == [str(root)]
