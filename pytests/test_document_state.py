"""The "modified" state of a document: the * in the titles and the prompt when it is closed with unsaved changes."""
import shutil

import pytest
from PyQt6.QtWidgets import QMessageBox

from ChildWindow import ChildWindow
from conftest import FIXTURES
from qt_helpers import open_documents, park_cursor, pump


@pytest.fixture
def prompts(monkeypatch):
    """The "Save changes?" questions that were asked (and answered No)."""
    asked = []

    def question(self, title='', text='', *args, **kwargs):
        asked.append(title)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(ChildWindow, 'questionCentered', question)
    return asked


@pytest.fixture
def workflow(window, tmp_path):
    """A copy of 50-workflow.cwl (so that nothing of the repository is touched) and its graph."""
    folder = tmp_path / 'wf'
    folder.mkdir()
    for name in ('echo.cwl', 'uppercase.cwl', '50-workflow.cwl'):
        shutil.copy(FIXTURES / name, folder / name)
    window.workspace.addFolder(str(folder))
    window.updateWorkspaceViews()
    park_cursor()
    window.openDocument(str(folder / '50-workflow.cwl'))
    pump(15)
    document = list(window.open_windows.values())[-1]
    pump(5)
    return document, document.workflow_editor.graph


def tab_text(window, document):
    return window.tabs.tabText(window.tabs.indexOf(document))


def test_editing_the_workflow_shows_the_star_at_once_and_asks_to_save_when_closing(window, workflow, prompts):
    document, graph = workflow
    assert not document.hasChanged and not tab_text(window, document).startswith('*')

    # an edit in the step inspector: no tab switch, no save
    graph.graph.get_node_by_name('echo').getCWL().label = 'Echo it'
    graph.editingFinished.emit()
    pump(8)
    assert document.hasChanged
    assert document.windowTitle().startswith('*') and tab_text(window, document).startswith('*')

    # undoing the edit makes the document the same as the saved one again
    graph.graph.get_node_by_name('echo').getCWL().label = None
    graph.editingFinished.emit()
    pump(8)
    assert not document.hasChanged and not document.windowTitle().startswith('*') and not tab_text(window, document).startswith('*')

    # deleting a step, then closing the tab without ever leaving the Visual Editor
    graph.graph.get_node_by_name('uppercase').set_selected(True)
    graph.deleteSelection()
    pump(10)
    assert document.hasChanged and tab_text(window, document).startswith('*')
    window.closeTab(window.tabs, window.tabs.indexOf(document))
    pump(8)
    assert prompts == ['Save Changes?']


def test_a_change_that_nothing_announced_is_still_found_when_closing(window, workflow, prompts):
    """Whoever changed the document, closing it checks the document itself, not a flag that may be out of date."""
    document, graph = workflow
    document.cwl_tool.label = 'Changed behind the back of the window'
    assert not document.hasChanged           # nobody refreshed the state
    window.closeTab(window.tabs, window.tabs.indexOf(document))
    pump(8)
    assert prompts == ['Save Changes?']


def test_moving_a_node_is_not_a_change_of_the_document(window, workflow, prompts):
    document, graph = workflow
    node = graph.graph.get_node_by_name('uppercase')
    node.set_pos(node.x_pos() + 120, node.y_pos() + 40)
    graph.editingFinished.emit()
    pump(8)
    assert not document.hasChanged
    window.closeTab(window.tabs, window.tabs.indexOf(document))
    pump(8)
    assert prompts == []


@pytest.mark.parametrize('name', ['echo.cwl', 'uppercase.cwl', '50-workflow.cwl', '51-workflow.cwl',
                                  '07-record.cwl', '09-arguments.cwl', '12-stdout.cwl'])
def test_a_document_that_was_not_touched_is_not_modified(window, prompts, name):
    document = open_documents(window, [name])[name]
    pump(10)
    assert not document.isModified() and not document.windowTitle().startswith('*')
    assert not tab_text(window, document).startswith('*')
    window.closeTab(window.tabs, window.tabs.indexOf(document))
    pump(6)
    assert prompts == [], f"{name} would ask to be saved although nothing was changed"


def test_adding_a_step_by_dropping_a_file_marks_the_document_modified(window, workflow, prompts, tmp_path):
    from PyQt6.QtCore import QPointF
    document, graph = workflow
    shutil.copy(FIXTURES / '01-hello-world.cwl', tmp_path / 'wf' / 'hello.cwl')
    document.workflow_editor.onAddStep(cwl_file=str(tmp_path / 'wf' / 'hello.cwl'), position=QPointF(300, 300))
    pump(12)
    assert document.hasChanged and tab_text(window, document).startswith('*')
    window.closeTab(window.tabs, window.tabs.indexOf(document))
    pump(8)
    assert prompts == ['Save Changes?']


def test_connecting_disconnecting_renaming_and_adding_outputs_mark_the_document_modified(window, workflow):
    from PyQt6.QtCore import QPointF
    document, graph = workflow
    nodes = {node.name(): node for node in graph.graph.all_nodes()}

    def fresh():
        document._mark_clean_snapshot()
        document.updateWindowTitle()
        pump(3)
        assert not document.hasChanged

    # drag from the output port of a step into empty canvas: a new workflow output
    fresh()
    graph.dragging_output_port = list(nodes['uppercase'].outputs().values())[0].view
    graph.createOutputNodeFromDrag(QPointF(900, 100))
    pump(10)
    assert document.hasChanged and tab_text(window, document).startswith('*')

    # rename a step
    fresh()
    node = graph.graph.get_node_by_name('echo')
    old_id = node.getCWL().id
    node.getCWL().id = (old_id.rsplit('#', 1)[0] + '#shout') if '#' in old_id else 'shout'
    graph.nodeEdited(node, old_id)
    pump(10)
    assert document.hasChanged


# ---------------------------------------------------------------------------------------- the Code tab
@pytest.fixture
def tool(window, tmp_path):
    """A copy of echo.cwl, shown in its Code tab, and the path of the copy."""
    folder = tmp_path / 'tool'
    folder.mkdir()
    shutil.copy(FIXTURES / 'echo.cwl', folder / 'echo.cwl')
    window.workspace.addFolder(str(folder))
    window.updateWorkspaceViews()
    park_cursor()
    window.openDocument(str(folder / 'echo.cwl'))
    pump(12)
    document = list(window.open_windows.values())[-1]
    document.tabs.setCurrentWidget(document.code_editor)
    pump(8)
    return document, folder / 'echo.cwl'


def type_label(document, label='Typed in the Code tab'):
    editor = document.code_editor.editor
    editor.setText(editor.text().replace('class: CommandLineTool', f'class: CommandLineTool\nlabel: {label}'))
    pump(8)


def test_typing_in_the_code_tab_marks_the_document_at_once(window, tool, prompts):
    document, path = tool
    assert not document.hasChanged and not tab_text(window, document).startswith('*')
    type_label(document)
    assert document.hasChanged
    assert document.windowTitle().startswith('*') and tab_text(window, document).startswith('*')
    # putting the text back as it was: the document is the saved one again
    editor = document.code_editor.editor
    editor.setText(editor.text().replace('\nlabel: Typed in the Code tab', ''))
    pump(8)
    assert not document.hasChanged and not tab_text(window, document).startswith('*')
    # typing again and closing from the Code tab, without leaving it
    type_label(document)
    window.closeTab(window.tabs, window.tabs.indexOf(document))
    pump(8)
    assert prompts == ['Save Changes?']


def test_save_keeps_what_was_typed_in_the_code_tab(window, tool):
    document, path = tool
    type_label(document)
    document.onMenuSaveFile(str(path), 'YAML')
    pump(8)
    assert 'Typed in the Code tab' in path.read_text(), "the file has the typed text"
    assert not document.hasChanged and not tab_text(window, document).startswith('*')
    assert not document.code_editor.hasUnappliedChanges()


def test_answering_yes_when_closing_saves_the_typed_text(window, tool, monkeypatch):
    document, path = tool
    monkeypatch.setattr(ChildWindow, 'questionCentered', lambda self, *a, **k: QMessageBox.StandardButton.Yes)
    type_label(document)
    window.closeTab(window.tabs, window.tabs.indexOf(document))
    pump(10)
    assert 'Typed in the Code tab' in path.read_text()
    assert document not in window.open_windows.values()


def test_text_that_is_not_valid_cwl_is_never_lost_silently(window, tool, monkeypatch):
    import qErrorMessage
    shown = []
    monkeypatch.setattr(qErrorMessage.QErrorMessage, 'show_critical', staticmethod(lambda *args, **kwargs: shown.append(args[1])))
    document, path = tool
    original = path.read_text()
    editor = document.code_editor.editor
    editor.setText(editor.text() + '\nfoo: [unclosed')
    pump(8)
    assert document.hasChanged and tab_text(window, document).startswith('*'), "half a line is a change too"
    document.onMenuSaveFile(str(path), 'YAML')
    pump(5)
    assert path.read_text() == original, "text that cannot be applied is not saved over the file"
    assert shown, "the user is told why"
    assert document.hasChanged
    # answering Yes when closing: the window stays, the typing is not lost
    monkeypatch.setattr(ChildWindow, 'questionCentered', lambda self, *a, **k: QMessageBox.StandardButton.Yes)
    window.closeTab(window.tabs, window.tabs.indexOf(document))
    pump(8)
    assert document in window.open_windows.values() and path.read_text() == original
    # answering No closes it
    monkeypatch.setattr(ChildWindow, 'questionCentered', lambda self, *a, **k: QMessageBox.StandardButton.No)
    window.closeTab(window.tabs, window.tabs.indexOf(document))
    pump(8)
    assert document not in window.open_windows.values()


def test_filling_the_code_tab_from_the_document_is_not_an_edit(window, tool):
    document, path = tool
    code = document.code_editor
    code.populateFromCWL()                   # what a redraw of the tab does
    pump(5)
    assert not document.hasChanged and not code.hasUnappliedChanges()
    code.changeTextFormat()                  # YAML <-> JSON
    pump(5)
    assert not document.hasChanged
