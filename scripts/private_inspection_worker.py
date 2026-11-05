"""No-network/no-model artifact inspector; invoked only via run_private."""
import hashlib
from pathlib import Path

from delivery.inspection import inspect_bytes, inspect_export_pair, summarize_report
from delivery.private_inspection import (CONTRACT, MAX_RESULT, _decode, _digest,
                                         _encoded, _require, validate_request, validate_result)
from delivery.storage import read_source_bytes


def main():
    job = Path.cwd()
    request = validate_request(_decode(read_source_bytes(job / 'request.json')))
    contents, reports = {}, {}
    for row in request['files']:
        content = read_source_bytes(job / row['filename'])
        _require(len(content) == row['size_bytes'] and
                 hashlib.sha256(content).hexdigest() == row['sha256'])
        contents[row['id']] = content
        reports[row['id']] = summarize_report(inspect_bytes(content, row['format']))
    formats = {row['id']: row['format'] for row in request['files']}
    pairs = [{**pair, 'report': inspect_export_pair(contents[pair['editable']],
              formats[pair['editable']], contents[pair['pdf']])} for pair in request['pairs']]
    result = {'contract': CONTRACT, 'input_digest': _digest(request), 'files': reports, 'pairs': pairs}
    raw = _encoded(validate_result(result, request))
    _require(len(raw) <= MAX_RESULT)
    (job / 'result.json').write_bytes(raw)


if __name__ == '__main__':
    main()
