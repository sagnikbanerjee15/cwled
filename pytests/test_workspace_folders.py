"""The workspace folders: the primary workspace and the copies that detached windows get."""
import os
from pathlib import Path

import pytest

import data
import workspaceFolders as wf


class FakeManager:
    """Stands in for the configuration manager: counts the saves."""
    saved = 0

    def saveConfiguration(self):
        FakeManager.saved += 1


@pytest.fixture
def folders(tmp_path, cwled_config, monkeypatch):
    for name in ('a', 'a/sub', 'a/sub/deep', 'b', 'c'):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)         # the primary workspace changes the working directory
    FakeManager.saved = 0
    data.configuration_manager = FakeManager()
    root = tmp_path.resolve()
    return {name: str(root / name) for name in ('a', 'a/sub', 'a/sub/deep', 'b', 'c')} | {'missing': str(root / 'missing')}


def test_primary_workspace_follows_the_module_functions(folders):
    a, b, sub, c = folders['a'], folders['b'], folders['a/sub'], folders['c']
    wf.initialise(a)
    assert wf.folders() == [a] and wf.currentFolder() == a and os.getcwd() == a
    assert wf.addFolder(b) == (wf.ADDED, [])
    assert wf.folders() == [a, b] and wf.currentFolder() == b and os.getcwd() == b
    assert FakeManager.saved == 1
    assert data.configuration['workspace_folders'] == [a, b] and data.configuration['workspace'] == a
    assert wf.addFolder(b)[0] == wf.DUPLICATE and wf.addFolder(sub)[0] == wf.NESTED
    assert wf.containingFolder(sub + '/x.cwl') == a and not wf.isInsideWorkspace(c + '/x.cwl')
    assert wf.removeFolder(b) and wf.currentFolder() == a and os.getcwd() == a
    assert isinstance(data.workspace_directory, Path)


def test_a_copy_is_independent_of_the_primary_workspace(folders):
    a, b = folders['a'], folders['b']
    wf.initialise(a)
    saved = FakeManager.saved
    copy = wf.PRIMARY.copy()
    assert type(copy) is wf.Workspace and copy.folders() == [a] and copy.currentFolder() == a
    copy.addFolder(b)
    assert copy.folders() == [a, b] and copy.currentFolder() == b
    assert wf.folders() == [a] and wf.currentFolder() == a and os.getcwd() == a, "the primary state and the cwd are untouched"
    assert FakeManager.saved == saved, "a copy never saves the configuration"


def test_merging_adds_the_folders_and_saves_the_primary_workspace(folders):
    a, b = folders['a'], folders['b']
    wf.initialise(a)
    copy = wf.PRIMARY.copy()
    copy.addFolder(b)
    saved = FakeManager.saved
    assert wf.PRIMARY.merge(copy.folders()) == [b]
    assert wf.folders() == [a, b] and wf.currentFolder() == a
    assert FakeManager.saved == saved + 1 and data.configuration['workspace_folders'] == [a, b]
    assert wf.PRIMARY.merge(copy.folders()) == [] and FakeManager.saved == saved + 1, "nothing to merge, nothing to save"


def test_merging_nested_folders(folders):
    a, sub, deep, b, c = (folders[k] for k in ('a', 'a/sub', 'a/sub/deep', 'b', 'c'))
    workspace = wf.Workspace([sub, c], current=sub)
    assert workspace.merge([deep]) == [] and workspace.folders() == [sub, c], "inside a root: skipped"
    assert workspace.merge([a]) == [a] and workspace.folders() == [a, c], "a parent takes the place of the root inside it"
    assert workspace.currentFolder() == a, "the current folder that was replaced follows"
    other = wf.Workspace([a, b], current=b)
    assert other.merge([folders['missing'], c]) == [c] and other.currentFolder() == b, "a folder that is gone is not merged"
    empty = wf.Workspace()
    assert empty.folders() == [] and empty.currentFolder() is None
    assert empty.merge([a]) == [a] and empty.currentFolder() == a


def test_removing_the_current_folder_of_a_copy(folders):
    a, b, c = folders['a'], folders['b'], folders['c']
    workspace = wf.Workspace([a, b, c], current=b)
    assert workspace.removeFolder(b) and workspace.currentFolder() == a and workspace.folders() == [a, c]
    assert workspace.removeFolder(a) and workspace.removeFolder(c) and workspace.currentFolder() is None
