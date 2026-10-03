"""User-run hidden prompt. Does not make API calls or change the live provider."""
import getpass
import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=['anthropic','deepseek','elasticsearch'], default='anthropic')
    args = parser.parse_args()
    if not sys.stdin.isatty():
        raise SystemExit('Run this in your own interactive terminal; never pass the key on the command line.')
    target = Path(__file__).resolve().parents[1] / 'deployment' / '.secrets' / (args.provider + '_api_key')
    if target.exists():
        raise SystemExit('A key file already exists. It was not overwritten.')
    key = getpass.getpass(args.provider.title() + ' API key (hidden): ').strip()
    prefix = {'anthropic':'sk-ant-','deepseek':'sk-','elasticsearch':''}[args.provider]
    if not key.startswith(prefix) or len(key)<16 or any(c.isspace() for c in key):
        raise SystemExit('That does not look like the selected provider API key. Nothing was saved.')
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.parent.chmod(0o700)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(key + '\n')
    print('API key saved privately. No API calls were made and the running service was not changed.')


if __name__ == '__main__':
    main()
