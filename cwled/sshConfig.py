"""
Reading the SSH client configuration (``~/.ssh/config``): the hosts it defines,
and which of them are EC2 instances.

Nothing here connects anywhere; the file is only read. It understands what the
OpenSSH client does with the entries a person writes by hand:

* ``Host`` lines with several names (``Host dev dev-2``); the names with a
  wildcard (``Host *``, ``Host *.example.com``) are not hosts of their own but
  settings for the hosts they match, and the first value found for an option
  wins, as in ssh (``IdentityFile`` adds up);
* ``Include`` (relative to ``~/.ssh``, with wildcards);
* ``Keyword value``, ``Keyword=value``, quoted values and comments.

``Match`` blocks are skipped.

An EC2 instance cannot be told from any other host with certainty, because the
file says nothing about it. The signs that are looked for (``SshHost.ec2_reasons``
says which one applies):

* certain: an AWS host name (``ec2-1-2-3-4.compute-1.amazonaws.com``, ``*.ec2.internal``,
  ``i-0123456789abcdef0``), a ProxyCommand through AWS (``aws ssm start-session``,
  EC2 Instance Connect), a comment or a name that says EC2 or AWS;
* probable: a ``.pem`` key (the key pair file of AWS) or the user name of an
  Amazon machine image (``ec2-user``, ``ubuntu``...) with a plain address.
"""
import fnmatch
import glob
import logging
import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

MAX_INCLUDE_DEPTH = 8

# how sure we are that a host is an EC2 instance
NOT_EC2 = 0
PROBABLY_EC2 = 1
EC2 = 2

# the user names of the Amazon machine images
AMI_USERS = {'ec2-user', 'ubuntu', 'admin', 'centos', 'fedora', 'rocky', 'almalinux', 'bitnami', 'alpine'}

_INSTANCE_ID = re.compile(r'^i-[0-9a-f]{8}([0-9a-f]{9})?$', re.IGNORECASE)
_IPV4 = re.compile(r'^\d{1,3}(\.\d{1,3}){3}$')
_AWS_WORD = re.compile(r'\b(ec2|aws|amazon)\b', re.IGNORECASE)
_AWS_PROXY = re.compile(r'aws\s+ssm|session-manager-plugin|ec2[-_]instance[-_]connect|\bmssh\b', re.IGNORECASE)


def defaultConfigPath() -> Path:
    """``~/.ssh/config`` of the user running the application."""
    return Path.home() / '.ssh' / 'config'


@dataclass
class SshHost:
    """A host of the SSH configuration, with the settings that apply to it."""
    alias: str                                  # what is typed after "ssh"
    hostname: str = ''                          # HostName (the alias when the file gives none)
    user: str = ''
    port: str = ''
    identity_files: List[str] = field(default_factory=list)
    proxy_jump: str = ''
    proxy_command: str = ''
    comment: str = ''                           # the comments written around its Host line
    source: str = ''                            # the file that defines it
    ec2_level: int = NOT_EC2
    ec2_reasons: List[str] = field(default_factory=list)

    @property
    def is_ec2(self) -> bool:
        """True for the hosts that are (probably) EC2 instances."""
        return self.ec2_level >= PROBABLY_EC2

    @property
    def destination(self) -> str:
        """``user@hostname:port``, the parts that are known."""
        text = self.hostname or self.alias
        if self.user:
            text = f"{self.user}@{text}"
        if self.port:
            text = f"{text}:{self.port}"
        return text


@dataclass
class SshConfig:
    """What was found in the configuration file."""
    path: Path
    exists: bool = False
    hosts: List[SshHost] = field(default_factory=list)
    files: List[str] = field(default_factory=list)      # the file and what it includes
    error: str = ''                                    # why the file could not be read

    def ec2Hosts(self) -> List[SshHost]:
        """The hosts that are (probably) EC2 instances, the certain ones first."""
        found = [host for host in self.hosts if host.is_ec2]
        return sorted(found, key=lambda host: -host.ec2_level)

    def host(self, alias: str) -> Optional[SshHost]:
        for host in self.hosts:
            if host.alias == alias:
                return host
        return None


# ------------------------------------------------------------------------------------------------ parsing
@dataclass
class _Block:
    """A ``Host`` block (or the lines before the first one): its patterns and options."""
    patterns: List[str]
    options: Dict[str, List[str]] = field(default_factory=dict)
    comments: List[str] = field(default_factory=list)
    source: str = ''


_LINE = re.compile(r'^(\w+)\s*=?\s*(.*)$')


def _tokens(text: str) -> List[str]:
    try:
        return shlex.split(text, comments=True, posix=True)
    except ValueError:                                # an unbalanced quote
        return text.split('#')[0].split()


def _hasWildcard(pattern: str) -> bool:
    return any(char in pattern for char in '*?') or pattern.startswith('!')


def _parseFile(path: Path, blocks: List[_Block], files: List[str], depth: int, visited: set):
    """Append the blocks of a configuration file (and of the files it includes) to ``blocks``."""
    resolved = str(path.resolve())
    if resolved in visited or depth > MAX_INCLUDE_DEPTH:
        return
    visited.add(resolved)
    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        lines = handle.read().splitlines()
    files.append(str(path))
    current: Optional[_Block] = None
    pending: List[str] = []                           # comment lines just above the next Host line
    skipping = False                                  # inside a Match block
    for raw in lines:
        line = raw.strip()
        if not line:
            pending = []
            continue
        if line.startswith('#'):
            comment = line.lstrip('#').strip()
            if raw[:1] in (' ', '\t') and current is not None and not skipping and current.patterns != ['*']:
                current.comments.append(comment)       # an indented comment belongs to the block it is in
            else:
                pending.append(comment)                # one at the left edge to the Host line below it
            continue
        match = _LINE.match(line)
        if not match:
            continue
        keyword, value = match.group(1).lower(), match.group(2)
        if keyword == 'host':
            skipping = False
            current = _Block(patterns=_tokens(value), comments=list(pending), source=str(path))
            # a comment after the Host line on the same line ("Host dev  # ec2") counts too
            if '#' in value:
                current.comments.append(value.split('#', 1)[1].strip())
            blocks.append(current)
            pending = []
            continue
        pending = []
        if keyword == 'match':
            skipping = True
            current = None
            continue
        if keyword == 'include':
            for pattern in _tokens(value):
                for included in _expandInclude(pattern, path):
                    try:
                        _parseFile(included, blocks, files, depth + 1, visited)
                    except OSError as e:
                        logger.warning(f"Cannot read {included}: {e}")
            continue
        if skipping:
            continue
        if current is None:
            current = _Block(patterns=['*'], source=str(path))        # the options before the first Host
            blocks.append(current)
        current.options.setdefault(keyword, []).extend(_tokens(value))


def _expandInclude(pattern: str, including: Path) -> List[Path]:
    """The files an Include line names: ``~`` and relative paths are relative to ``~/.ssh``, wildcards expand."""
    expanded = os.path.expanduser(pattern)
    if not os.path.isabs(expanded):
        expanded = str(Path.home() / '.ssh' / expanded)
    return [Path(found) for found in sorted(glob.glob(expanded)) if os.path.isfile(found)]


def _applies(block: _Block, alias: str) -> bool:
    positive = [p for p in block.patterns if not p.startswith('!')]
    negative = [p[1:] for p in block.patterns if p.startswith('!')]
    if any(fnmatch.fnmatchcase(alias, p) for p in negative):
        return False
    return any(fnmatch.fnmatchcase(alias, p) for p in positive)


def _resolve(alias: str, defining: _Block, blocks: List[_Block]) -> SshHost:
    """The settings of a host: the first value of each option, over the blocks that apply, in file order."""
    options: Dict[str, List[str]] = {}
    for block in blocks:
        if not _applies(block, alias):
            continue
        for keyword, values in block.options.items():
            if keyword == 'identityfile':
                options.setdefault(keyword, []).extend(values)
            else:
                options.setdefault(keyword, values)

    def first(keyword: str) -> str:
        values = options.get(keyword)
        return values[0] if values else ''

    hostname = first('hostname').replace('%h', alias) or alias
    host = SshHost(
        alias=alias,
        hostname=hostname,
        user=first('user'),
        port=first('port'),
        identity_files=list(options.get('identityfile', [])),
        proxy_jump=first('proxyjump'),
        proxy_command=' '.join(options.get('proxycommand', [])),
        comment=' '.join(comment for comment in defining.comments if comment),
        source=defining.source,
    )
    classify(host)
    return host


def readSshConfig(path: Optional[os.PathLike] = None) -> SshConfig:
    """
    Read the SSH configuration (by default ``~/.ssh/config``): the hosts it defines and, for
    each, whether it is an EC2 instance. A file that does not exist gives no host and no error.
    """
    config_path = Path(path) if path is not None else defaultConfigPath()
    config = SshConfig(path=config_path)
    try:
        if not config_path.is_file():
            return config
    except OSError as e:                                  # e.g. no permission to look into ~/.ssh
        config.error = f"{config_path} cannot be read: {e}"
        return config
    config.exists = True
    blocks: List[_Block] = []
    try:
        _parseFile(config_path, blocks, config.files, 0, set())
    except OSError as e:
        config.error = f"{config_path} cannot be read: {e}"
        return config
    seen = set()
    for block in blocks:
        for pattern in block.patterns:
            if _hasWildcard(pattern) or pattern in seen:
                continue
            seen.add(pattern)
            config.hosts.append(_resolve(pattern, block, blocks))
    return config


# ------------------------------------------------------------------------------------------------ EC2
def classify(host: SshHost) -> SshHost:
    """Set ``ec2_level`` and ``ec2_reasons`` of a host from what the configuration says about it."""
    certain: List[str] = []
    probable: List[str] = []
    name = (host.hostname or '').lower()
    if name.endswith('.amazonaws.com') or name.endswith('.amazonaws.com.cn'):
        certain.append(f"the host name {host.hostname} is an AWS name")
    elif name.endswith('.ec2.internal') or name.endswith('.compute.internal'):
        certain.append(f"the host name {host.hostname} is an internal EC2 name")
    elif _INSTANCE_ID.match(name):
        certain.append(f"the host name {host.hostname} is an EC2 instance id")
    if host.proxy_command and _AWS_PROXY.search(host.proxy_command):
        certain.append("it is reached through AWS (Session Manager or EC2 Instance Connect)")
    if host.proxy_jump and _AWS_WORD.search(host.proxy_jump):
        probable.append(f"it is reached through {host.proxy_jump}")
    if host.comment and _AWS_WORD.search(host.comment):
        certain.append("its comment mentions EC2 or AWS")
    if any(token.lower() in ('ec2', 'aws') for token in re.split(r'[^A-Za-z0-9]+', host.alias)):
        certain.append("its name mentions EC2 or AWS")
    pem = any(identity.lower().endswith('.pem') for identity in host.identity_files)
    if pem:
        probable.append("it uses a .pem key (the key pair file of AWS)")
    if host.user.lower() in AMI_USERS and (pem or _IPV4.match(name)):
        probable.append(f"its user {host.user} is the default of an Amazon machine image")
    host.ec2_reasons = certain + probable
    host.ec2_level = EC2 if certain else (PROBABLY_EC2 if probable else NOT_EC2)
    return host
