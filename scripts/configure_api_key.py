"""User-run hidden prompt. Does not make API calls or change the live provider."""
import getpass
import os
from pathlib import Path
import sys


def main():
    if not sys.stdin.isatty():
        raise SystemExit('Run this in your own interactive terminal; never pass the key on the command line.')
    target = Path(__file__).resolve().parents[1] / 'deployment' / '.secrets' / 'anthropic_api_key'
    if target.exists():
        raise SystemExit('A key file already exists. It was not overwritten.')
    key = getpass.getpass('Anthropic API key (hidden): ').strip()
    if not key.startswith('sk-ant-') or any(c.isspace() for c in key):
        raise SystemExit('That does not look like an Anthropic API key. Nothing was saved.')
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.parent.chmod(0o700)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(key + '\n')
    print('API key saved privately. No API calls were made and the running service was not changed.')


if __name__ == '__main__':
    main()
