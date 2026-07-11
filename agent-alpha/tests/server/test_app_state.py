from pathlib import Path

from agent.core.agent_runtime import PROJECT_ROOT
from agent.server.stores.app_state import AppStateStore


def test_managed_project_workspace_uses_project_id(tmp_path):
    store = AppStateStore(tmp_path / "state.json")

    project = store.create_project(name="Alpha")

    workspace = Path(project["workspace_path"])
    assert project["id"] in workspace.parts
    assert workspace == PROJECT_ROOT / "workspace" / "projects" / project["id"]
    assert workspace.exists()
    assert project["workspace_kind"] == "managed"


def test_external_project_keeps_explicit_workspace(tmp_path):
    store = AppStateStore(tmp_path / "state.json")
    external = tmp_path / "external workspace"

    project = store.create_project(name="External", workspace_path=str(external))

    assert Path(project["workspace_path"]) == external.resolve()
    assert project["workspace_kind"] == "external"
    assert external.exists()


def test_external_project_uses_folder_name_when_name_is_empty(tmp_path):
    store = AppStateStore(tmp_path / "state.json")
    external = tmp_path / "chosen-folder"

    project = store.create_project(name="", workspace_path=str(external))

    assert project["name"] == "chosen-folder"


def test_corrupt_state_file_falls_back_to_local_admin(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{broken", encoding="utf-8")
    store = AppStateStore(path)

    assert store.list_users()[0]["id"] == "local_admin"
    assert store.get_settings()["permission_mode"] == "ask"


def test_delete_project_removes_record_but_keeps_workspace_files(tmp_path):
    store = AppStateStore(tmp_path / "state.json")
    workspace = tmp_path / "external"
    project = store.create_project(name="External", workspace_path=str(workspace))
    important_file = workspace / "keep.txt"
    important_file.write_text("do not delete", encoding="utf-8")

    assert store.delete_project(project["id"]) is True

    assert store.get_project(project["id"]) is None
    assert important_file.read_text(encoding="utf-8") == "do not delete"


def test_list_projects_keeps_pinned_projects_first(tmp_path):
    store = AppStateStore(tmp_path / "state.json")

    first = store.create_project(name="First")
    second = store.create_project(name="Second")
    store.update_project(first["id"], {"is_pinned": True})

    projects = store.list_projects()

    assert [project["id"] for project in projects[:2]] == [first["id"], second["id"]]
    assert projects[0]["is_pinned"] is True


def test_update_settings_keeps_api_keys_per_provider(tmp_path):
    store = AppStateStore(tmp_path / "state.json")

    openai = store.update_settings({"llm_provider": "openai", "llm_api_key": "openai-key"})
    deepseek = store.update_settings({"llm_provider": "deepseek", "llm_api_key": "deepseek-key"})
    custom = store.update_settings({"llm_provider": "custom"})

    assert openai["llm_api_key"] == "openai-key"
    assert deepseek["llm_api_key"] == "deepseek-key"
    assert custom["llm_api_key"] == ""
    assert custom["llm_api_keys"]["openai"] == "openai-key"
    assert custom["llm_api_keys"]["deepseek"] == "deepseek-key"
