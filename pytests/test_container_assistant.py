"""
The container assistant: image references, the answers of the registries and the buttons of the Docker field.

No test reaches the network. ``urllib.request.urlopen`` is replaced by ``FakeRegistry``, which answers
from a table of replies and records every request.
"""
import io
import json
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QObject, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QWidget

import containerRegistry as cr
from qt_helpers import open_documents, pump, wait_until
from widgets.qDocker import QDockerWidget

DIGEST = 'sha256:' + 'a' * 64
OTHER_DIGEST = 'sha256:' + 'b' * 64
SAMTOOLS_TAG = '1.19--h50ea8bc_0'
SAMTOOLS_IMAGE = f'quay.io/biocontainers/samtools:{SAMTOOLS_TAG}'

HUB_MANIFEST = 'https://registry-1.docker.io/v2/library/ubuntu/manifests/22.04'
HUB_CHALLENGE = ('Bearer realm="https://auth.docker.io/token",service="registry.docker.io",'
                 'scope="repository:library/ubuntu:pull"')
HUB_TOKEN = 'https://auth.docker.io/token?' + urllib.parse.urlencode(
    {'service': 'registry.docker.io', 'scope': 'repository:library/ubuntu:pull'})


def quay_tag(repository: str, tag: str) -> str:
    return f'https://quay.io/api/v1/repository/{repository}/tag/?specificTag={tag}'


def biocontainers_tags(tool: str) -> str:
    return f'https://quay.io/api/v1/repository/biocontainers/{tool}/tag/?limit=20&onlyActiveTags=true'


class Reply:
    def __init__(self, status: int = 200, body: bytes = b'', headers: dict = None):
        self.status = status
        self.body = body
        self.headers = headers or {}


def json_reply(payload, status: int = 200) -> Reply:
    return Reply(status, json.dumps(payload).encode())


def tag_answer(name: str, digest: str = DIGEST) -> dict:
    return {'tags': [{'name': name, 'manifest_digest': digest}]}


class FakeAnswer:
    def __init__(self, reply: Reply):
        self.status = reply.status
        self.headers = reply.headers
        self._body = reply.body

    def read(self, size: int = -1) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeRegistry:
    """
    Stands in for ``urllib.request.urlopen``. Replies are looked up by the full URL, query included.
    A request that carries an Authorization header gets the reply in ``authorised`` when there is one.
    An exception in the table is raised, as a network failure is; an unknown URL answers 404.
    """

    def __init__(self, monkeypatch):
        self.replies = {}
        self.authorised = {}
        self.requests = []
        self.gate = None                    # an Event the answers wait for: the window is tested while it is pending
        self.started = threading.Event()
        monkeypatch.setattr(urllib.request, 'urlopen', self)

    def __call__(self, request, timeout=None):
        url = request.full_url
        authorisation = request.get_header('Authorization')
        self.requests.append(SimpleNamespace(method=request.get_method(), url=url,
                                             authorisation=authorisation, timeout=timeout))
        self.started.set()
        if self.gate is not None:
            self.gate.wait(10)
        table = self.authorised if authorisation and url in self.authorised else self.replies
        reply = table.get(url, Reply(404))
        if isinstance(reply, BaseException):
            raise reply
        if reply.status >= 400:
            raise urllib.error.HTTPError(url, reply.status, 'error', reply.headers, io.BytesIO(reply.body))
        return FakeAnswer(reply)

    def urls(self) -> list:
        return [request.url for request in self.requests]


@pytest.fixture
def network(monkeypatch):
    return FakeRegistry(monkeypatch)


# ------------------------------------------------------------------------------- image references
@pytest.mark.parametrize('text, registry, repository, name, tag, digest', [
    ('ubuntu:22.04', 'docker.io', 'library/ubuntu', 'ubuntu', '22.04', None),
    ('library/ubuntu', 'docker.io', 'library/ubuntu', 'library/ubuntu', None, None),
    ('ubuntu', 'docker.io', 'library/ubuntu', 'ubuntu', None, None),
    ('docker.io/ubuntu:22.04', 'docker.io', 'library/ubuntu', 'docker.io/ubuntu', '22.04', None),
    ('myuser/tool:1.0', 'docker.io', 'myuser/tool', 'myuser/tool', '1.0', None),
    (SAMTOOLS_IMAGE, 'quay.io', 'biocontainers/samtools', 'quay.io/biocontainers/samtools', SAMTOOLS_TAG, None),
    ('localhost:5000/team/app:v1', 'localhost:5000', 'team/app', 'localhost:5000/team/app', 'v1', None),
    ('registry.example.com:5000/app', 'registry.example.com:5000', 'app', 'registry.example.com:5000/app', None, None),
    (f'ubuntu@{DIGEST}', 'docker.io', 'library/ubuntu', 'ubuntu', None, DIGEST),
    (f'ubuntu:22.04@{DIGEST}', 'docker.io', 'library/ubuntu', 'ubuntu', '22.04', DIGEST),
])
def test_an_image_is_split_into_registry_repository_tag_and_digest(text, registry, repository, name, tag, digest):
    reference = cr.parseImageReference(text)
    assert (reference.registry, reference.repository, reference.name, reference.tag, reference.digest) == \
        (registry, repository, name, tag, digest)


def test_an_image_without_a_tag_is_the_latest_one():
    assert cr.parseImageReference('ubuntu').effectiveTag == 'latest'
    assert cr.parseImageReference('ubuntu:22.04').effectiveTag == '22.04'


@pytest.mark.parametrize('text', ['', '   ', 'ubuntu:', 'Ubuntu', 'two words', '$(inputs.image)',
                                  'ubuntu@sha256:xyz', 'quay.io/', 'ubuntu:1.0:2', 'quay.io/Bio/tool'])
def test_text_that_is_not_an_image_reference_is_refused(text):
    with pytest.raises(ValueError):
        cr.parseImageReference(text)


def test_the_display_shows_the_image_with_its_tag_and_digest():
    assert cr.parseImageReference(f'ubuntu:22.04@{DIGEST}').display == f'ubuntu:22.04@{DIGEST}'


# -------------------------------------------------------------------------------- the answers
def test_a_quay_tag_answer_gives_the_digest_of_that_tag():
    payload = {'tags': [{'name': '1.18', 'manifest_digest': OTHER_DIGEST}, {'name': '1.19', 'manifest_digest': DIGEST}]}
    assert cr.manifestFromQuayTags(payload, '1.19') == cr.Manifest(DIGEST)


@pytest.mark.parametrize('payload', [{'tags': []}, {'tags': [{'name': '1.18', 'manifest_digest': DIGEST}]}, {}])
def test_a_quay_answer_without_the_tag_is_not_found(payload):
    assert cr.manifestFromQuayTags(payload, '1.19') is None


def test_a_quay_tag_without_a_digest_is_found_without_one():
    assert cr.manifestFromQuayTags({'tags': [{'name': '1.19'}]}, '1.19') == cr.Manifest(None)


def test_the_digest_header_is_read_whatever_the_case_of_its_name():
    assert cr.digestFromHeaders({'Docker-Content-Digest': DIGEST}) == DIGEST
    assert cr.digestFromHeaders({'docker-content-digest': DIGEST}) == DIGEST
    assert cr.digestFromHeaders({}) is None
    assert cr.digestFromHeaders({'docker-content-digest': 'not a digest'}) is None


def test_a_login_challenge_is_parsed():
    challenge = cr.parseChallenge(HUB_CHALLENGE)
    assert challenge.scheme == 'Bearer'
    assert challenge.params == {'realm': 'https://auth.docker.io/token', 'service': 'registry.docker.io',
                                'scope': 'repository:library/ubuntu:pull'}
    assert cr.parseChallenge(None) is None


def test_the_token_of_a_login_answer_is_read_under_either_name():
    assert cr.tokenFromPayload({'token': 'one'}) == 'one'
    assert cr.tokenFromPayload({'access_token': 'two'}) == 'two'
    with pytest.raises(ValueError):
        cr.tokenFromPayload({'other': 'three'})


def test_biocontainers_tags_come_newest_first():
    payload = {'tags': [{'name': '1.0', 'start_ts': 100}, {'name': '2.0', 'start_ts': 300},
                        {'name': '0.9'}, {'name': 3}]}
    assert [tag.name for tag in cr.parseBioContainersTags(payload)] == ['2.0', '1.0', '0.9']


@pytest.mark.parametrize('commands, tool', [
    ([{'command': '/usr/bin/Samtools view'}], 'samtools'),
    (['bwa mem'], 'bwa'),
    ([{'command': ''}, {'command': 'javac'}], 'javac'),
    ([], None),
    ([{'command': '$(inputs.tool) x'}], None),
    ([{'command': 'dir/'}], None),
])
def test_the_tool_is_the_first_word_of_the_base_command(commands, tool):
    assert cr.firstToolName(commands) == tool


# ------------------------------------------------------------------------ requests and replies
def test_check_finds_an_image_on_quay_and_its_digest(network):
    network.replies[quay_tag('biocontainers/samtools', SAMTOOLS_TAG)] = json_reply(tag_answer(SAMTOOLS_TAG))
    check = cr.checkImage(SAMTOOLS_IMAGE)
    assert check.status == cr.FOUND and check.digest == DIGEST
    assert DIGEST in check.message
    assert network.urls() == [quay_tag('biocontainers/samtools', SAMTOOLS_TAG)]


def test_check_follows_the_login_challenge_of_docker_hub(network):
    network.replies[HUB_MANIFEST] = Reply(401, headers={'WWW-Authenticate': HUB_CHALLENGE})
    network.replies[HUB_TOKEN] = json_reply({'token': 'anonymous'})
    network.authorised[HUB_MANIFEST] = Reply(200, headers={'Docker-Content-Digest': DIGEST})
    check = cr.checkImage('ubuntu:22.04')
    assert check.status == cr.FOUND and check.digest == DIGEST
    assert [(request.method, request.url) for request in network.requests] == \
        [('HEAD', HUB_MANIFEST), ('GET', HUB_TOKEN), ('HEAD', HUB_MANIFEST)]
    assert network.requests[2].authorisation == 'Bearer anonymous'


def test_check_says_an_image_that_is_not_there_is_not_found(network):
    network.replies[quay_tag('biocontainers/samtools', 'no-such')] = json_reply({'tags': []})
    check = cr.checkImage('quay.io/biocontainers/samtools:no-such')
    assert check.status == cr.NOT_FOUND and check.digest is None
    assert 'not in quay.io' in check.message


def test_check_says_a_missing_repository_is_not_found(network):
    network.replies[quay_tag('biocontainers/nothing', '1')] = Reply(404)
    assert cr.checkImage('quay.io/biocontainers/nothing:1').status == cr.NOT_FOUND


@pytest.mark.parametrize('failure', [urllib.error.URLError('offline'), socket.timeout('timed out'),
                                     ConnectionResetError('reset')])
def test_check_reports_a_registry_that_cannot_be_reached(network, failure):
    network.replies[quay_tag('biocontainers/samtools', SAMTOOLS_TAG)] = failure
    check = cr.checkImage(SAMTOOLS_IMAGE)
    assert check.status == cr.UNREACHABLE and check.digest is None
    assert check.message.startswith('Could not reach the registry')


def test_check_reports_a_registry_that_asks_for_a_login_as_unreachable(network):
    network.replies[HUB_MANIFEST] = Reply(401, headers={'WWW-Authenticate': 'Basic realm="registry"'})
    assert cr.checkImage('ubuntu:22.04').status == cr.UNREACHABLE
    assert network.urls() == [HUB_MANIFEST]


def test_check_reports_a_login_that_gives_no_token_as_unreachable(network):
    network.replies[HUB_MANIFEST] = Reply(401, headers={'WWW-Authenticate': HUB_CHALLENGE})
    network.replies[HUB_TOKEN] = Reply(401)
    assert cr.checkImage('ubuntu:22.04').status == cr.UNREACHABLE


def test_check_of_a_registry_without_a_digest_header_is_found_without_digest(network):
    network.replies[HUB_MANIFEST] = Reply(200)
    check = cr.checkImage('ubuntu:22.04')
    assert check.status == cr.FOUND and check.digest is None
    assert 'no digest' in check.message


def test_a_text_that_is_not_a_reference_makes_no_request(network):
    assert cr.checkImage('Ubuntu').status == cr.INVALID
    assert network.requests == []


def test_every_request_has_the_timeout_and_goes_through_urlopen(network):
    network.replies[quay_tag('biocontainers/samtools', SAMTOOLS_TAG)] = json_reply(tag_answer(SAMTOOLS_TAG))
    cr.checkImage(SAMTOOLS_IMAGE)
    assert cr.TIMEOUT == 8
    assert [request.timeout for request in network.requests] == [8]


def test_biocontainers_tags_are_listed_newest_first(network):
    network.replies[biocontainers_tags('samtools')] = json_reply({'tags': [
        {'name': '1.18', 'manifest_digest': OTHER_DIGEST, 'start_ts': 10},
        {'name': SAMTOOLS_TAG, 'manifest_digest': DIGEST, 'start_ts': 20},
    ]})
    result = cr.listBioContainersTags('samtools')
    assert result.status == cr.FOUND
    assert [tag.name for tag in result.tags] == [SAMTOOLS_TAG, '1.18']
    assert network.urls() == [biocontainers_tags('samtools')]


def test_a_tool_without_a_biocontainers_repository_is_not_found(network):
    network.replies[biocontainers_tags('nothing')] = Reply(404)
    result = cr.listBioContainersTags('nothing')
    assert result.status == cr.NOT_FOUND and 'no BioContainers image named nothing' in result.message


def test_the_tag_list_reports_an_offline_registry(network):
    network.replies[biocontainers_tags('samtools')] = urllib.error.URLError('offline')
    assert cr.listBioContainersTags('samtools').status == cr.UNREACHABLE


def test_a_tool_name_that_is_not_a_name_makes_no_request(network):
    assert cr.listBioContainersTags('sam tools; rm').status == cr.INVALID
    assert network.requests == []


def test_pin_writes_the_digest_in_place_of_the_tag(network):
    network.replies[quay_tag('biocontainers/samtools', SAMTOOLS_TAG)] = json_reply(tag_answer(SAMTOOLS_TAG))
    pin = cr.pinImage(SAMTOOLS_IMAGE)
    assert pin.pinned == f'quay.io/biocontainers/samtools@{DIGEST}'
    assert SAMTOOLS_TAG in pin.message, "the tag stays in view, outside the field"


def test_pin_of_an_image_that_is_pinned_already_makes_no_request(network):
    pin = cr.pinImage(f'ubuntu@{DIGEST}')
    assert pin.pinned is None and 'already pinned' in pin.message
    assert network.requests == []


def test_pin_gives_the_reason_when_the_digest_cannot_be_resolved(network):
    network.replies[HUB_MANIFEST] = urllib.error.URLError('offline')
    pin = cr.pinImage('ubuntu:22.04')
    assert pin.pinned is None and pin.message.startswith('Could not reach the registry')


def test_pin_gives_no_text_when_the_registry_has_no_digest(network):
    network.replies[HUB_MANIFEST] = Reply(200)
    assert cr.pinImage('ubuntu:22.04').pinned is None


# ------------------------------------------------------------------------------- the buttons
class ToolEditorStandIn(QWidget):
    """The docker widget finds the base command through its parents, as in the tool editor."""

    def __init__(self, commands: list):
        super().__init__()
        self.basecommand = SimpleNamespace(getData=lambda: commands)


class Spy(QObject):
    """Counts the editingFinished signals of the Docker widget (what the tool editor listens to)."""

    def __init__(self, widget):
        super().__init__()
        self.count = 0
        widget.editingFinished.connect(self.bump)

    def bump(self):
        self.count += 1


@pytest.fixture
def docker(cwled_config, qapp):
    """A Docker widget in a tool with the given base command; make(image, commands) returns the widget."""
    owners = []

    def make(image: str = '', commands=('samtools view',)):
        owner = ToolEditorStandIn([{'command': command, 'order': 0, 'entry_order': index}
                                   for index, command in enumerate(commands)])
        owners.append(owner)
        widget = QDockerWidget(parent=owner, cwl_version='v1.2')
        widget.docker_image.setText(image)
        owner.show()
        pump()
        return widget

    yield make
    for owner in owners:
        owner.close()


@pytest.fixture
def choose(monkeypatch):
    """
    Answers the chooser: ``choose(tag)`` picks that tag and accepts; ``choose(None, accepted=False)`` cancels.
    The tag the chooser selects to start with is appended to ``shown``.
    """
    shown = []

    def install(tag=None, accepted=True, opened=None):
        def run(self):
            if opened is not None:
                opened.append(self._tool)
            shown.append(self.chosenImage())
            if tag:
                self.selectTag(tag)
            return 1 if accepted else 0
        monkeypatch.setattr(cr.BioContainersChooser, 'exec', run)
        return shown
    return install


def settled(widget, text: str):
    """Wait until the result label says ``text`` and the lookup has ended."""
    assistant = widget.assistant
    wait_until(lambda: text in assistant.resultLabel.text() and assistant.checkButton.isEnabled(),
               message=f'the result did not say {text!r}: {assistant.resultLabel.text()!r}')


def test_nothing_is_requested_by_opening_or_editing_a_tool(network, docker):
    widget = docker('ubuntu:22.04')
    QTest.keyClicks(widget.docker_image.line_edit, '.1')
    QTest.keyClick(widget.docker_image.line_edit, Qt.Key.Key_Return)
    pump()
    assert network.requests == []
    assert widget.assistant.checkButton.text() == 'Check image'


def test_opening_a_tool_with_a_docker_requirement_requests_nothing(network, make_window):
    window = make_window()
    documents = open_documents(window, ['09-arguments.cwl'])
    assert '09-arguments.cwl' in documents
    assert network.requests == []


def test_check_image_shows_the_digest_next_to_the_field(network, docker):
    network.replies[quay_tag('biocontainers/samtools', SAMTOOLS_TAG)] = json_reply(tag_answer(SAMTOOLS_TAG))
    widget = docker(SAMTOOLS_IMAGE)
    widget.assistant.checkButton.click()
    settled(widget, 'Found')
    assert DIGEST in widget.assistant.resultLabel.text()
    assert [request.method for request in network.requests] == ['GET']


def test_check_image_says_an_image_is_not_there(network, docker):
    network.replies[quay_tag('biocontainers/samtools', 'no-such')] = json_reply({'tags': []})
    widget = docker('quay.io/biocontainers/samtools:no-such')
    widget.assistant.checkButton.click()
    settled(widget, 'not in quay.io')


def test_check_image_says_when_the_registry_cannot_be_reached(network, docker):
    network.replies[quay_tag('biocontainers/samtools', SAMTOOLS_TAG)] = urllib.error.URLError('offline')
    widget = docker(SAMTOOLS_IMAGE)
    widget.assistant.checkButton.click()
    settled(widget, 'Could not reach the registry')


def test_the_window_stays_responsive_while_the_registry_is_asked(network, docker):
    network.gate = threading.Event()
    network.replies[quay_tag('biocontainers/samtools', SAMTOOLS_TAG)] = json_reply(tag_answer(SAMTOOLS_TAG))
    widget = docker(SAMTOOLS_IMAGE)
    widget.assistant.checkButton.click()
    wait_until(network.started.is_set, message='the request did not start')
    pump()
    assert not widget.assistant.checkButton.isEnabled() and not widget.assistant.suggestButton.isEnabled()
    assert not widget.assistant.pinButton.isEnabled()
    assert 'Asking the registry' in widget.assistant.resultLabel.text()
    network.gate.set()
    settled(widget, 'Found')


def test_suggest_fills_the_field_with_the_tag_chosen(network, docker, choose):
    network.replies[biocontainers_tags('samtools')] = json_reply({'tags': [
        {'name': '1.18', 'manifest_digest': OTHER_DIGEST, 'start_ts': 10},
        {'name': SAMTOOLS_TAG, 'manifest_digest': DIGEST, 'start_ts': 20},
    ]})
    shown = choose(tag='1.18')
    widget = docker('', commands=('/usr/bin/samtools view',))
    changes = Spy(widget)
    widget.assistant.suggestButton.click()
    wait_until(lambda: changes.count == 1, message='the field was not changed')
    assert widget.docker_image.text() == 'quay.io/biocontainers/samtools:1.18'
    assert shown == [f'quay.io/biocontainers/samtools:{SAMTOOLS_TAG}'], "the newest tag is selected to start with"
    assert network.urls() == [biocontainers_tags('samtools')]


def test_cancelling_the_chooser_changes_nothing(network, docker, choose):
    network.replies[biocontainers_tags('samtools')] = json_reply(tag_answer(SAMTOOLS_TAG))
    choose(accepted=False)
    widget = docker('ubuntu:22.04', commands=('samtools',))
    changes = Spy(widget)
    widget.assistant.suggestButton.click()
    settled(widget, '')
    assert widget.docker_image.text() == 'ubuntu:22.04' and changes.count == 0


def test_suggest_without_a_base_command_asks_nothing(network, docker):
    widget = docker('', commands=())
    widget.assistant.suggestButton.click()
    settled(widget, 'Set the base command first')
    assert network.requests == []


def test_suggest_offline_says_so_and_opens_no_chooser(network, docker, choose):
    network.replies[biocontainers_tags('samtools')] = urllib.error.URLError('offline')
    opened = []
    choose(opened=opened)
    widget = docker('', commands=('samtools',))
    widget.assistant.suggestButton.click()
    settled(widget, 'Could not reach the registry')
    assert opened == [] and widget.docker_image.text() == ''


def test_suggest_for_a_tool_without_an_image_says_so(network, docker, choose):
    network.replies[biocontainers_tags('nothing')] = Reply(404)
    opened = []
    choose(opened=opened)
    widget = docker('', commands=('nothing',))
    widget.assistant.suggestButton.click()
    settled(widget, 'no BioContainers image named nothing')
    assert opened == []


def test_pin_digest_writes_the_digest_in_place_of_the_tag(network, docker):
    network.replies[quay_tag('biocontainers/samtools', SAMTOOLS_TAG)] = json_reply(tag_answer(SAMTOOLS_TAG))
    widget = docker(SAMTOOLS_IMAGE)
    changes = Spy(widget)
    widget.assistant.pinButton.click()
    settled(widget, 'Pinned')
    assert widget.docker_image.text() == f'quay.io/biocontainers/samtools@{DIGEST}'
    assert changes.count == 1, "the tool is updated, as after typing"
    assert SAMTOOLS_TAG in widget.assistant.resultLabel.text()
    assert not widget.assistant.pinButton.isEnabled(), "a pinned image is not pinned again"


def test_retyping_the_field_undoes_the_pin(network, docker):
    network.replies[quay_tag('biocontainers/samtools', SAMTOOLS_TAG)] = json_reply(tag_answer(SAMTOOLS_TAG))
    widget = docker(SAMTOOLS_IMAGE)
    widget.assistant.pinButton.click()
    settled(widget, 'Pinned')
    widget.docker_image.setText(SAMTOOLS_IMAGE)
    assert widget.assistant.pinButton.isEnabled()


def test_pin_is_disabled_with_the_reason_when_the_digest_cannot_be_resolved(network, docker):
    network.replies[quay_tag('biocontainers/samtools', SAMTOOLS_TAG)] = urllib.error.URLError('offline')
    widget = docker(SAMTOOLS_IMAGE)
    assert widget.assistant.pinButton.isEnabled(), "nothing is requested before the click"
    widget.assistant.pinButton.click()
    settled(widget, 'Could not reach the registry')
    assert not widget.assistant.pinButton.isEnabled()
    assert 'Could not reach the registry' in widget.assistant.pinButton.toolTip()
    widget.docker_image.setText('ubuntu:22.04')
    assert widget.assistant.pinButton.isEnabled(), "it is tried again once the field changes"


@pytest.mark.parametrize('image', ['', 'Ubuntu'])
def test_pin_is_disabled_for_a_field_that_is_not_an_image(network, docker, image):
    widget = docker(image)
    assert not widget.assistant.pinButton.isEnabled()
    assert widget.assistant.pinButton.toolTip().startswith('Not an image reference')
    assert network.requests == []


def test_the_tool_editor_suggests_the_image_of_its_own_base_command(network, make_window, choose):
    window = make_window()
    network.replies[biocontainers_tags('javac')] = json_reply(tag_answer('9.0'))
    shown = choose(tag='9.0')
    document = open_documents(window, ['09-arguments.cwl'])['09-arguments.cwl']
    docker = document.app_editor.docker_image
    assert network.requests == []
    docker.assistant.suggestButton.click()
    wait_until(lambda: docker.docker_image.text() == 'quay.io/biocontainers/javac:9.0', message='not suggested')
    assert shown == ['quay.io/biocontainers/javac:9.0']
    assert network.urls() == [biocontainers_tags('javac')]
