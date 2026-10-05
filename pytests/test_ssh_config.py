"""Reading ~/.ssh/config: the hosts, and which of them are EC2 instances. Only files of the tests are read."""
from pathlib import Path

import pytest

import sshConfig
from sshConfig import EC2, NOT_EC2, PROBABLY_EC2, readSshConfig

SAMPLE = """\
# EC2 dev box (us-east-1)
Host dev
    HostName 54.12.34.56
    User ec2-user
    IdentityFile ~/.ssh/dev.pem

Host build-box
    HostName ec2-3-90-1-2.compute-1.amazonaws.com
    User ubuntu
    Port 2222
    IdentityFile "~/.ssh/my key.pem"

# the laptop of a colleague
Host laptop
    HostName 192.168.1.20

Host private-1 private-2
    HostName %h.ec2.internal
    ProxyJump bastion

Host ssm-box
    HostName i-0123456789abcdef0
    ProxyCommand sh -c "aws ssm start-session --target %h --document-name AWS-StartSSHSession"

Host onlypem
    HostName 1.2.3.4
    IdentityFile ~/.ssh/k.pem

Host aws-prod # prod
    HostName prod.example.com

Host *.corp
    User corpuser

Host x.corp
    HostName x.corp.example.com

Match host foo
    User nobody

Host *
    ServerAliveInterval 30
    User fallback

Include conf.d/*
"""


@pytest.fixture
def ssh_home(tmp_path, monkeypatch):
    """A fake home with ~/.ssh/config (and an included file); the real one is never read."""
    home = tmp_path / 'home'
    (home / '.ssh' / 'conf.d').mkdir(parents=True)
    (home / '.ssh' / 'config').write_text(SAMPLE)
    (home / '.ssh' / 'conf.d' / 'extra').write_text(
        "Host included\n    HostName ec2-1-1-1-1.eu-west-1.compute.amazonaws.com\n")
    monkeypatch.setenv('HOME', str(home))
    return home


def hosts_by_alias(config):
    return {host.alias: host for host in config.hosts}


def test_the_hosts_of_the_file_and_of_what_it_includes_are_read(ssh_home):
    config = readSshConfig()
    assert config.path == ssh_home / '.ssh' / 'config' and config.exists and not config.error
    assert [Path(f).name for f in config.files] == ['config', 'extra']
    # wildcard blocks (Host *, Host *.corp) are settings, not hosts; Match blocks are skipped
    assert [h.alias for h in config.hosts] == ['dev', 'build-box', 'laptop', 'private-1', 'private-2', 'ssm-box',
                                               'onlypem', 'aws-prod', 'x.corp', 'included']


def test_the_settings_of_a_host_follow_the_rules_of_ssh(ssh_home):
    hosts = hosts_by_alias(readSshConfig())
    build = hosts['build-box']
    assert (build.hostname, build.user, build.port) == ('ec2-3-90-1-2.compute-1.amazonaws.com', 'ubuntu', '2222')
    assert build.identity_files == ['~/.ssh/my key.pem']                 # quotes are understood
    assert build.destination == 'ubuntu@ec2-3-90-1-2.compute-1.amazonaws.com:2222'
    assert hosts['dev'].user == 'ec2-user'                              # the first value wins ...
    assert hosts['laptop'].user == 'fallback'                           # ... and "Host *" fills the rest
    assert hosts['x.corp'].user == 'corpuser'                           # "Host *.corp" applies to x.corp
    assert hosts['private-2'].hostname == 'private-2.ec2.internal'      # %h is the name that was typed
    assert hosts['laptop'].user != 'nobody'                             # a Match block is not used


def test_which_hosts_are_ec2_instances_and_why(ssh_home):
    hosts = hosts_by_alias(readSshConfig())
    assert hosts['build-box'].ec2_level == EC2 and 'AWS name' in hosts['build-box'].ec2_reasons[0]
    assert hosts['dev'].ec2_level == EC2 and any('comment' in r for r in hosts['dev'].ec2_reasons)
    assert hosts['private-1'].ec2_level == EC2                          # *.ec2.internal
    assert hosts['ssm-box'].ec2_level == EC2                            # an instance id, reached through SSM
    assert hosts['aws-prod'].ec2_level == EC2                           # the name says aws
    assert hosts['included'].ec2_level == EC2
    assert hosts['onlypem'].ec2_level == PROBABLY_EC2                   # only a .pem key
    assert hosts['laptop'].ec2_level == NOT_EC2 and hosts['laptop'].ec2_reasons == []
    assert hosts['x.corp'].ec2_level == NOT_EC2
    found = [h.alias for h in readSshConfig().ec2Hosts()]
    assert 'laptop' not in found and 'x.corp' not in found
    assert found.index('onlypem') > found.index('included'), "the certain ones come first"


def test_a_comment_belongs_to_the_host_below_it_not_the_one_above(tmp_path):
    config_file = tmp_path / 'config'
    config_file.write_text("Host first\n    HostName a.example.com\n# an EC2 instance for the build\nHost second\n"
                           "    HostName b.example.com\n")
    hosts = hosts_by_alias(readSshConfig(config_file))
    assert hosts['first'].ec2_level == NOT_EC2 and hosts['second'].ec2_level == EC2


def test_no_file_gives_no_hosts_and_no_error(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    config = readSshConfig()
    assert not config.exists and config.hosts == [] and config.error == ''
    assert config.path == tmp_path / '.ssh' / 'config'


def test_an_include_loop_and_odd_lines_do_not_break_the_reading(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    config_file = tmp_path / 'config'
    config_file.write_text(f'Include {config_file}\nHost = spaced\n  HostName="quoted name"\nHost "unbalanced\n'
                           f'Host ok\n  HostName ec2-1-2-3-4.compute-1.amazonaws.com\n')
    config = readSshConfig(config_file)
    assert 'ok' in hosts_by_alias(config) and hosts_by_alias(config)['ok'].is_ec2
