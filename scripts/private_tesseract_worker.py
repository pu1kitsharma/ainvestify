"""Exact-file network-denied PDF OCR worker; never call outside run_private."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from delivery.linux_ocr import BINARY, LANGUAGE, CONTRACT, MAX_PAGES, MAX_PIXELS, checked_request, _write


def main():
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CPU, (105, 105))
    resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64_000_000, 64_000_000))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    job = Path.cwd()
    frozen = (job / 'request.json').read_bytes()
    request = json.loads(frozen)
    content = checked_request(request)
    deadline = time.monotonic() + 100
    import pypdfium2
    pages = []
    with pypdfium2.PdfDocument(content) as document:
        if not 1 <= len(document) <= MAX_PAGES or max(request['page_numbers']) > len(document):
            raise ValueError('OCR source page count exceeds declared bounds')
        total = len(document)
        for number in request['page_numbers']:
            page = document[number-1]
            try:
                width_points, height_points = page.get_width(), page.get_height()
                scale = request['width'] / width_points
                if math.ceil(width_points*scale)*math.ceil(height_points*scale) > MAX_PIXELS:
                    raise ValueError('OCR page raster pixel limit exceeded')
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil()
                    width, height = image.size
                    image_path = job / ('page_%04d.png' % number)
                    image.save(image_path)
                finally:
                    bitmap.close()
                environment = {'PATH':'/usr/bin:/bin','HOME':str(job),'TMPDIR':str(job),
                               'LANG':'C.UTF-8','OMP_THREAD_LIMIT':'1','TESSDATA_PREFIX':str(LANGUAGE.parent)}
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('OCR cumulative batch budget exhausted')
                raw_path=job/('page_%04d.tsv'%number)
                error_path=job/('page_%04d.stderr'%number)
                with raw_path.open('xb') as raw_output,error_path.open('xb') as error_output:
                    result = subprocess.run(['/usr/bin/prlimit','--fsize=8000000:8000000','--',
                        str(BINARY),str(image_path),'stdout','-l','eng','--psm','3',
                        '-c','load_system_dawg=0','-c','load_freq_dawg=0','tsv'],
                        cwd=job,env=environment,stdout=raw_output,stderr=error_output,timeout=min(25,remaining))
                if result.returncode or raw_path.stat().st_size>8_000_000:
                    raise RuntimeError('Confined OCR engine failed')
                raw=raw_path.read_bytes()
                pages.append({'page':number,'width_pixels':width,'height_pixels':height,
                    'width_points':width_points,'height_points':height_points,
                    'image_sha256':hashlib.sha256(image_path.read_bytes()).hexdigest(),
                    'tsv_sha256':hashlib.sha256(raw).hexdigest()})
            finally:
                page.close()
    _write(job / 'result.json', {'contract':CONTRACT,'request_sha256':hashlib.sha256(frozen).hexdigest(),
        'source_sha256':request['source_sha256'],'total_pages':total,'pages':pages})


if __name__ == '__main__':
    main()
