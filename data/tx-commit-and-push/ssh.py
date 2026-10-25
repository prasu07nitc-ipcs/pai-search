"""Fixed, noninteractive GitHub SSH transport; executed via a runner-owned launcher."""
from __future__ import annotations
import os
import re
import sys


def command(arguments, known_hosts):
    args = list(arguments)
    if args[:2] == ['-o', 'SendEnv=GIT_PROTOCOL']:
        args = args[2:]
    if (len(args) != 2 or args[0] != 'git@github.com'
            or not re.fullmatch(r"git-receive-pack '[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+\.git'", args[1])):
        raise ValueError('Only GitHub receive-pack is permitted by this SSH transport.')
    return ['/usr/bin/ssh', '-F', '/dev/null', '-o', 'BatchMode=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'UpdateHostKeys=no',
            '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'UserKnownHostsFile=' + known_hosts,
            '-o', 'IdentityFile=none', '-o', 'PasswordAuthentication=no',
            '-o', 'KbdInteractiveAuthentication=no', '-o', 'PreferredAuthentications=publickey',
            '-o', 'ForwardAgent=no', '-o', 'ClearAllForwardings=yes',
            '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
            '-o', 'ProxyCommand=none', '-o', 'ProxyJump=none',
            '-o', 'ConnectTimeout=15', *args]


def main():
    try:
        args = command(sys.argv[1:], os.environ['PROJECT_DATA_SSH_KNOWN_HOSTS'])
    except (ValueError, KeyError):
        raise SystemExit('SSH transport not configured or arguments rejected.') from None
    # No shell, key-file loading, host-key writes, password or passphrase prompts.
    os.execv(args[0], args)


if __name__ == '__main__':
    main()
