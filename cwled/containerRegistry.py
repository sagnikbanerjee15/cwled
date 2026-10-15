"""
The container assistant of the tool editor: checks Docker images against their registries.

The Docker image field of a CommandLineTool has three buttons (see ``ContainerAssistant``):

- **Check image** asks the registry whether the image exists, and its digest;
- **Suggest BioContainers image** lists the newest tags of ``quay.io/biocontainers/<tool>``, where the
  tool is the first word of the base command, and fills the field with the tag chosen;
- **Pin digest** rewrites the field as ``image@sha256:...``, the digest the image has now.

Only those buttons ask a registry for anything, and each request runs in a worker thread, so the
window keeps responding. The parsing (``parseImageReference``, ``manifestFromQuayTags``,
``parseBioContainersTags``...) takes text or decoded JSON and never touches the network; the tests
replace ``urllib.request.urlopen``. Requests go through ``urlopen``, which honours the proxy variables
of the environment (``HTTPS_PROXY``, ``NO_PROXY``...), and each waits at most ``TIMEOUT`` seconds.

Failures that are expected here (offline, a missing image, a registry that asks for a login) are
results, not errors: they are logged as warnings.
"""
import http.client
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from PyQt6 import sip
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

logger = logging.getLogger(__name__)

TIMEOUT = 8                       # seconds a registry has to answer
MAX_BODY = 2_000_000              # bytes of an answer that are read
DOCKER_HUB = 'docker.io'          # the registry of an image written without a host
DOCKER_HUB_NAMES = ('docker.io', 'index.docker.io', 'registry-1.docker.io')
DOCKER_HUB_API = 'registry-1.docker.io'
QUAY = 'quay.io'
BIOCONTAINERS = 'biocontainers'
MANIFEST_ACCEPT = ', '.join([
    'application/vnd.oci.image.index.v1+json',
    'application/vnd.oci.image.manifest.v1+json',
    'application/vnd.docker.distribution.manifest.list.v2+json',
    'application/vnd.docker.distribution.manifest.v2+json',
])

FOUND, NOT_FOUND, UNREACHABLE, INVALID = 'found', 'not_found', 'unreachable', 'invalid'

_COMPONENT = re.compile(r'[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*')   # one path part of an image name
_HOST = re.compile(r'[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*(?::[0-9]+)?')  # a registry, with an optional port
_TAG = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}')
_DIGEST = re.compile(r'[a-z0-9]+:[0-9a-f]{32,}')
_TOOL = re.compile(r'[a-z0-9][a-z0-9._-]*')                         # a BioContainers repository name
_CHALLENGE_PARAM = re.compile(r'(\w+)="([^"]*)"')


# ------------------------------------------------------------------------------------------ parsing
@dataclass(frozen=True)
class ImageReference:
    '''An image as written in the Docker field, split into its parts.'''
    registry: str            # the host it is pulled from; Docker Hub is 'docker.io'
    repository: str          # the path in that registry, e.g. 'library/ubuntu'
    name: str                # the image as written, without tag and digest: 'ubuntu', 'quay.io/biocontainers/samtools'
    tag: Optional[str]       # None when the reference has no tag
    digest: Optional[str]    # 'sha256:...' when the reference has one

    @property
    def effectiveTag(self) -> str:
        '''The tag a registry looks at when none is written.'''
        return self.tag or 'latest'

    @property
    def apiHost(self) -> str:
        '''The host that answers the registry API (Docker Hub's is not docker.io).'''
        return DOCKER_HUB_API if self.registry == DOCKER_HUB else self.registry

    @property
    def registryName(self) -> str:
        return 'Docker Hub' if self.registry == DOCKER_HUB else self.registry

    @property
    def display(self) -> str:
        '''The image as the messages show it: name, tag and digest.'''
        text = self.name
        if self.tag:
            text += f':{self.tag}'
        if self.digest:
            text += f'@{self.digest}'
        return text


def parseImageReference(text: Optional[str]) -> ImageReference:
    '''
    Split an image as written (``ubuntu:22.04``, ``quay.io/biocontainers/samtools:1.19--h50ea8bc_0``,
    ``localhost:5000/team/app@sha256:...``) into registry, repository, tag and digest.

    The first part is a registry only when it has a dot or a port, or is ``localhost``, as in Docker;
    otherwise the image is on Docker Hub, where a single name stands for ``library/<name>``.

    Raises ValueError, with the reason, when the text is not an image reference.
    '''
    value = (text or '').strip()
    if not value:
        raise ValueError('the field is empty')
    if any(character.isspace() for character in value):
        raise ValueError(f'{value!r} contains a space')
    path, at, digest = value.partition('@')
    if at and not _DIGEST.fullmatch(digest):
        raise ValueError(f'the digest {digest!r} is not of the form sha256:<hex>')

    given_registry = None
    first, slash, rest = path.partition('/')
    if slash and ('.' in first or ':' in first or first == 'localhost'):
        given_registry, path = first, rest
        if not _HOST.fullmatch(given_registry):
            raise ValueError(f'{given_registry!r} is not a registry host')

    head, _, last = path.rpartition('/')
    name, colon, tag = last.partition(':')
    if not name:
        raise ValueError(f'{value!r} has no image name')
    if colon and not _TAG.fullmatch(tag):
        raise ValueError(f'the tag {tag!r} is not valid')

    registry = DOCKER_HUB if given_registry is None or given_registry in DOCKER_HUB_NAMES else given_registry
    repository = '/'.join(part for part in (head, name) if part)
    for part in repository.split('/'):
        if not _COMPONENT.fullmatch(part):
            raise ValueError(f'{part!r} is not a valid name: use lower-case letters, digits, "." "_" and "-"')
    if registry == DOCKER_HUB and '/' not in repository:
        repository = f'library/{repository}'

    written = '/'.join(part for part in (given_registry, head, name) if part)
    return ImageReference(registry=registry, repository=repository, name=written,
                          tag=tag if colon else None, digest=digest if at else None)


@dataclass(frozen=True)
class Manifest:
    '''An image found in its registry, with its digest when the registry says it.'''
    digest: Optional[str]


@dataclass(frozen=True)
class BioContainerTag:
    name: str
    digest: Optional[str]
    started: int             # seconds since the epoch; 0 when Quay does not say


@dataclass(frozen=True)
class Challenge:
    scheme: str              # e.g. 'Bearer'
    params: dict             # e.g. {'realm': ..., 'service': ..., 'scope': ...}


def _digestOrNone(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and _DIGEST.fullmatch(value) else None


def _listOf(payload: Any, key: str) -> list:
    value = payload.get(key) if isinstance(payload, dict) else None
    return value if isinstance(value, list) else []


def manifestFromQuayTags(payload: Any, tag: str) -> Optional[Manifest]:
    '''
    The answer of Quay's tag API for one tag: the manifest of that tag, or None when the
    repository has no such tag (Quay answers with an empty list then).
    '''
    for entry in _listOf(payload, 'tags'):
        if isinstance(entry, dict) and entry.get('name') == tag:
            return Manifest(_digestOrNone(entry.get('manifest_digest')))
    return None


def parseBioContainersTags(payload: Any) -> list[BioContainerTag]:
    '''The tags of Quay's tag API, newest first.'''
    tags = []
    for entry in _listOf(payload, 'tags'):
        if not isinstance(entry, dict) or not isinstance(entry.get('name'), str):
            continue
        started = entry.get('start_ts')
        tags.append(BioContainerTag(entry['name'], _digestOrNone(entry.get('manifest_digest')),
                                    started if isinstance(started, int) else 0))
    return sorted(tags, key=lambda tag: tag.started, reverse=True)


def digestFromHeaders(headers: Mapping[str, str]) -> Optional[str]:
    '''The digest a registry returns for a manifest, in its Docker-Content-Digest header.'''
    return _digestOrNone({key.lower(): value for key, value in headers.items()}.get('docker-content-digest'))


def parseChallenge(header: Optional[str]) -> Optional[Challenge]:
    '''A WWW-Authenticate challenge, e.g. ``Bearer realm="https://...",service="...",scope="..."``.'''
    if not header:
        return None
    scheme, _, rest = header.strip().partition(' ')
    return Challenge(scheme, dict(_CHALLENGE_PARAM.findall(rest)))


def tokenFromPayload(payload: Any) -> str:
    '''The token in the answer of a registry's login service (``token`` or ``access_token``).'''
    for key in ('token', 'access_token'):
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, str) and value:
            return value
    raise ValueError('the login answer has no token')


def firstToolName(commands: list) -> Optional[str]:
    '''
    The tool a base command runs: the first word of the first command, without its directory
    (``/usr/bin/Samtools view`` is ``samtools``). None when no command starts with a valid name.
    '''
    for command in commands or []:
        text = command.get('command', '') if isinstance(command, dict) else command
        words = text.split() if isinstance(text, str) else []
        if words:
            name = words[0].rsplit('/', 1)[-1].lower()
            return name if _TOOL.fullmatch(name) else None
    return None


# ------------------------------------------------------------------------------------- requests
class RegistryUnreachable(Exception):
    '''The registry could not be asked: it is offline or too slow, or it asks for a login.'''


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict            # the header names in lower case
    body: bytes


def _lowerKeys(headers: Any) -> dict:
    return {key.lower(): value for key, value in headers.items()} if headers is not None else {}


def _request(method: str, url: str, headers: Optional[dict] = None) -> Response:
    '''One request. An answer with an error status is returned, not raised; a network failure is raised.'''
    request = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            body = answer.read(MAX_BODY) if method == 'GET' else b''
            return Response(answer.status, _lowerKeys(answer.headers), body)
    except urllib.error.HTTPError as error:       # an HTTPError is also the answer of the server
        try:
            return Response(error.code, _lowerKeys(error.headers), b'')
        finally:
            error.close()
    except (OSError, http.client.HTTPException) as error:
        reason = getattr(error, 'reason', error)
        host = urllib.parse.urlsplit(url).hostname
        raise RegistryUnreachable(f'{host} did not answer ({reason})') from error


def _json(response: Response, host: str) -> Any:
    if response.status != 200:
        raise RegistryUnreachable(f'{host} answered {response.status}')
    try:
        return json.loads(response.body.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as error:
        raise RegistryUnreachable(f'{host} sent an answer that is not JSON') from error


def _fetch(method: str, url: str, host: str, repository: str, headers: Optional[dict] = None) -> Response:
    '''
    Ask a registry. When it answers 401 with a Bearer challenge, as Docker Hub and most public
    registries do, an anonymous token is fetched from the realm named in the challenge and the
    request is sent again with it. Any other request for a login is a failure.
    '''
    headers = dict(headers or {})
    response = _request(method, url, headers)
    if response.status == 401:
        challenge = parseChallenge(response.headers.get('www-authenticate'))
        realm = challenge.params.get('realm', '') if challenge else ''
        is_bearer = challenge is not None and challenge.scheme.lower() == 'bearer'
        if not is_bearer or urllib.parse.urlsplit(realm).scheme not in ('http', 'https'):
            raise RegistryUnreachable(f'{host} asks for a login')
        query = urllib.parse.urlencode({
            'service': challenge.params.get('service', host),
            'scope': challenge.params.get('scope', f'repository:{repository}:pull'),
        })
        try:
            token = tokenFromPayload(_json(_request('GET', f'{realm}?{query}'), host))
        except ValueError as error:
            raise RegistryUnreachable(f'{host} gave no anonymous login') from error
        response = _request(method, url, {**headers, 'Authorization': f'Bearer {token}'})
    if response.status in (401, 403):
        raise RegistryUnreachable(f'{host} asks for a login')
    return response


def _manifestV2(reference: ImageReference) -> Optional[Manifest]:
    '''The manifest of an image in a registry that speaks the v2 API (HEAD, falling back to GET).'''
    host = reference.apiHost
    url = f'https://{host}/v2/{reference.repository}/manifests/{reference.digest or reference.effectiveTag}'
    headers = {'Accept': MANIFEST_ACCEPT}
    response = _fetch('HEAD', url, host, reference.repository, headers)
    if response.status == 405:                     # the registry does not take HEAD
        response = _fetch('GET', url, host, reference.repository, headers)
    if response.status == 404:
        return None
    if response.status != 200:
        raise RegistryUnreachable(f'{host} answered {response.status}')
    return Manifest(digestFromHeaders(response.headers))


def _manifestQuay(reference: ImageReference) -> Optional[Manifest]:
    '''A tag of an image on Quay, through Quay's own API (anonymous for public repositories).'''
    query = urllib.parse.urlencode({'specificTag': reference.effectiveTag})
    response = _request('GET', f'https://{QUAY}/api/v1/repository/{reference.repository}/tag/?{query}')
    if response.status == 404:
        return None
    return manifestFromQuayTags(_json(response, QUAY), reference.effectiveTag)


def manifestOf(reference: ImageReference) -> Optional[Manifest]:
    '''The image in its registry, or None when the registry does not have it.'''
    if reference.registry == QUAY and reference.digest is None:
        return _manifestQuay(reference)
    return _manifestV2(reference)


# ----------------------------------------------------------------------------- what the GUI shows
@dataclass(frozen=True)
class ImageCheck:
    status: str              # FOUND, NOT_FOUND, UNREACHABLE or INVALID
    digest: Optional[str]
    message: str


def checkImage(text: str) -> ImageCheck:
    '''Whether the image written in ``text`` exists in its registry, and its digest.'''
    try:
        reference = parseImageReference(text)
    except ValueError as error:
        return ImageCheck(INVALID, None, f'Not an image reference: {error}.')
    try:
        manifest = manifestOf(reference)
    except RegistryUnreachable as error:
        logger.warning('Could not check %s: %s', text, error)
        return ImageCheck(UNREACHABLE, None, f'Could not reach the registry: {error}.')
    if manifest is None:
        return ImageCheck(NOT_FOUND, None, f'{reference.display} is not in {reference.registryName}.')
    if manifest.digest:
        return ImageCheck(FOUND, manifest.digest, f'Found {reference.display}, digest {manifest.digest}.')
    return ImageCheck(FOUND, None, f'Found {reference.display}. The registry gave no digest.')


@dataclass(frozen=True)
class TagList:
    status: str              # FOUND, NOT_FOUND, UNREACHABLE or INVALID
    tags: list               # of BioContainerTag, newest first
    message: str


def listBioContainersTags(tool: str) -> TagList:
    '''The newest active tags of ``quay.io/biocontainers/<tool>``.'''
    if not _TOOL.fullmatch(tool):
        return TagList(INVALID, [], f'{tool!r} is not a tool name.')
    query = urllib.parse.urlencode({'limit': 20, 'onlyActiveTags': 'true'})
    try:
        response = _request('GET', f'https://{QUAY}/api/v1/repository/{BIOCONTAINERS}/{tool}/tag/?{query}')
        if response.status == 404:
            return TagList(NOT_FOUND, [], f'There is no BioContainers image named {tool} on quay.io.')
        tags = parseBioContainersTags(_json(response, QUAY))
    except RegistryUnreachable as error:
        logger.warning('Could not list the BioContainers tags of %s: %s', tool, error)
        return TagList(UNREACHABLE, [], f'Could not reach the registry: {error}.')
    if not tags:
        return TagList(NOT_FOUND, [], f'BioContainers has no active tags for {tool}.')
    return TagList(FOUND, tags, f'The {len(tags)} newest tags of {tool}.')


@dataclass(frozen=True)
class Pin:
    pinned: Optional[str]    # the text for the field, image@sha256:..., or None when it cannot be pinned
    message: str


def pinImage(text: str) -> Pin:
    '''
    The image written as ``image@digest``, with the digest the registry has for its tag now.
    The tag is dropped from the field; the message keeps it in view.
    '''
    try:
        reference = parseImageReference(text)
    except ValueError as error:
        return Pin(None, f'Not an image reference: {error}.')
    if reference.digest:
        return Pin(None, f'{reference.display} is already pinned to a digest.')
    check = checkImage(text)
    if check.digest is None:
        return Pin(None, check.message)
    tag = f':{reference.tag}' if reference.tag else ''
    return Pin(f'{reference.name}@{check.digest}', f'Pinned {reference.name}{tag} to {check.digest}.')


# -------------------------------------------------------------------------- the Qt side
_running: set = set()        # lookups in progress; kept alive until their thread has finished


class _Lookup(QThread):
    '''Runs one lookup of this module in a worker thread and hands its result to the GUI thread.'''
    done = pyqtSignal(object)

    def __init__(self, function: Callable[[str], Any], argument: str):
        super().__init__()
        self._function = function
        self._argument = argument

    def run(self):
        try:
            result = self._function(self._argument)
        except Exception:        # not an expected failure but a bug: the error log shows it
            logger.exception('The container lookup of %r failed', self._argument)
            result = None
        self.done.emit(result)


class BioContainersChooser(QDialog):
    '''The newest BioContainers tags of a tool; the newest is selected to start with.'''

    def __init__(self, tool: str, tags: list, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle('Suggest BioContainers image')
        self._tool = tool
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f'Newest images of {tool} on BioContainers ({QUAY}/{BIOCONTAINERS}/{tool}):'))
        self.tagList = QListWidget(self)
        for tag in tags:
            self.tagList.addItem(QListWidgetItem(tag.name))
        self.tagList.setCurrentRow(0)
        self.tagList.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.tagList)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(420, 320)

    def selectTag(self, tag: str):
        matches = self.tagList.findItems(tag, Qt.MatchFlag.MatchExactly)
        if matches:
            self.tagList.setCurrentItem(matches[0])

    def chosenImage(self) -> Optional[str]:
        item = self.tagList.currentItem()
        return f'{QUAY}/{BIOCONTAINERS}/{self._tool}:{item.text()}' if item else None


class ContainerAssistant(QWidget):
    '''
    The buttons under the Docker image field, and the result of the last one.

    ``field`` is the QLabelLineEditWidget holding the image; ``commands`` returns the base command
    rows of the tool, read when Suggest is clicked. Only Pin digest and Suggest change the field,
    and then emit ``imageChanged``, so that the tool is updated as after typing.
    '''
    imageChanged = pyqtSignal()

    def __init__(self, field, commands: Callable[[], list], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._field = field
        self._commands = commands
        self._busy = False
        self._failedPin: Optional[tuple] = None      # (text, reason) of a pin that could not be resolved

        self.checkButton = QPushButton('Check image', self)
        self.suggestButton = QPushButton('Suggest BioContainers image', self)
        self.pinButton = QPushButton('Pin digest', self)
        self.resultLabel = QLabel(self)
        self.resultLabel.setWordWrap(True)
        self.resultLabel.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        for button in (self.checkButton, self.suggestButton, self.pinButton):
            row.addWidget(button)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row)
        layout.addWidget(self.resultLabel)

        self.checkButton.clicked.connect(self.onCheckClicked)
        self.suggestButton.clicked.connect(self.onSuggestClicked)
        self.pinButton.clicked.connect(self.onPinClicked)
        field.textChanged.connect(self.updatePinButton)
        self.updatePinButton()

    def updatePinButton(self):
        '''Pin digest is enabled for an image without a digest, unless its digest has just failed to resolve.'''
        refusal = self._pinRefusal()
        self.pinButton.setEnabled(not self._busy and refusal is None)
        self.pinButton.setToolTip(refusal or 'Write the digest of this image into the field, as image@sha256:...')

    def _pinRefusal(self) -> Optional[str]:
        text = self._field.text()
        try:
            reference = parseImageReference(text)
        except ValueError as error:
            return f'Not an image reference: {error}.'
        if reference.digest:
            return 'The image is already pinned to a digest. Type the image again to change it.'
        if self._failedPin and self._failedPin[0] == text:
            return self._failedPin[1]
        return None

    def onCheckClicked(self):
        self._start(checkImage, self._field.text(), self._showMessage)

    def onSuggestClicked(self):
        tool = firstToolName(self._commands())
        if tool is None:
            self.resultLabel.setText('Set the base command first: its first word names the tool on BioContainers, such as samtools.')
            return
        self._start(listBioContainersTags, tool, lambda tags: self._offerTags(tool, tags))

    def onPinClicked(self):
        text = self._field.text()
        self._start(pinImage, text, lambda pin: self._showPin(text, pin))

    def _start(self, function: Callable[[str], Any], argument: str, handler: Callable[[Any], None]):
        self._setBusy(True)
        self.resultLabel.setText('Asking the registry...')
        lookup = _Lookup(function, argument)
        _running.add(lookup)
        lookup.done.connect(lambda result: self._finish(handler, result))
        lookup.finished.connect(lambda: _running.discard(lookup))
        lookup.start()

    def _finish(self, handler: Callable[[Any], None], result: Any):
        if sip.isdeleted(self):
            return
        self._setBusy(False)
        if result is None:
            self.resultLabel.setText('The lookup failed; the log has the details.')
            return
        handler(result)

    def _setBusy(self, busy: bool):
        self._busy = busy
        self.checkButton.setEnabled(not busy)
        self.suggestButton.setEnabled(not busy)
        self.updatePinButton()

    def _showMessage(self, result: ImageCheck):
        self.resultLabel.setText(result.message)

    def _offerTags(self, tool: str, result: TagList):
        if result.status != FOUND:
            self.resultLabel.setText(result.message)
            return
        chooser = BioContainersChooser(tool, result.tags, self)
        if chooser.exec() and chooser.chosenImage():
            image = chooser.chosenImage()
            self._setImage(image)
            self.resultLabel.setText(f'Set to {image}.')
        else:
            self.resultLabel.setText('')

    def _showPin(self, text: str, pin: Pin):
        if self._field.text() != text:
            self.resultLabel.setText('The image changed while its digest was looked up: click Pin digest again.')
            return
        if pin.pinned is None:
            self._failedPin = (text, pin.message)
            self.updatePinButton()
            self.resultLabel.setText(pin.message)
            return
        self._setImage(pin.pinned)
        self.resultLabel.setText(pin.message)

    def _setImage(self, image: str):
        self._failedPin = None
        self._field.setText(image)
        self.imageChanged.emit()
        self.updatePinButton()
