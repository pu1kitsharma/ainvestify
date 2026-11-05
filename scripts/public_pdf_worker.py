"""Offline, exact-byte public PDF parser. No fetcher, DB, API identity or model."""
import hashlib
import json
from pathlib import Path

from delivery.public_pdf import (CONTRACT, MAX_RESULT, PublicPDFError, decode,
                                 parse_pdf_payload, validate_request)
from delivery.storage import read_source_bytes


def main():
    job = Path.cwd()
    request = validate_request(decode(read_source_bytes(job / 'request.json')))
    body = read_source_bytes(job / 'input.bin')
    if len(body) != request['size_bytes'] or hashlib.sha256(body).hexdigest() != request['sha256']:
        raise PublicPDFError('invalid_request')
    try:
        page, state = parse_pdf_payload(body), 'ok'
    except PublicPDFError as exc:
        page, state = None, 'insufficient_text' if str(exc) == 'insufficient_text' else 'parse_failed'
    raw = json.dumps({**request, 'state': state, 'page': page}, allow_nan=False).encode()
    if len(raw) > MAX_RESULT:
        raise PublicPDFError('invalid_result')
    (job / 'result.json').write_bytes(raw)


if __name__ == '__main__':
    main()
