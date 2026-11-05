"""Literal OCR provenance, complete coverage and denial boundaries."""
from copy import deepcopy
import json
import platform
import sys

import pytest

from delivery import linux_ocr as ocr

HEADER = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'


def tsv(text='Synthetic', confidence='92', x='10'):
    return (HEADER+'1\t1\t0\t0\t0\t0\t0\t0\t200\t100\t-1\t\n'
            + '5\t1\t1\t1\t1\t1\t'+x+'\t20\t40\t15\t'+confidence+'\t'+text+'\n').encode()


def test_literal_observations_preserve_words_and_bottom_left_geometry():
    rows = ocr.parse_tsv(tsv('Projected'), 200, 100)
    assert rows == [{'text':'Projected','confidence':.92,'bbox':[.05,.65,.2,.15]}]
    assert 'verified' not in rows[0]


@pytest.mark.parametrize('raw,width,height', [(tsv(confidence='nan'),200,100),
    (tsv(confidence='101'),200,100), (tsv(x='190'),200,100),
    (b'not a TSV',200,100), (tsv(),True,100), (tsv(),5000,5000)])
def test_malformed_or_unbounded_observations_fail_closed(raw,width,height):
    with pytest.raises((ValueError,UnicodeError)):
        ocr.parse_tsv(raw,width,height)


def test_incomplete_or_duplicate_page_batches_cannot_be_complete(monkeypatch):
    base = {'source_sha256':'a'*64,'total_pages':2,'pages':[{'page':1}]}
    monkeypatch.setattr(ocr,'replay_pdf_batch',lambda path:deepcopy(base))
    with pytest.raises(ValueError,match='coverage'):
        ocr.combine_pdf_batches(['one'])
    with pytest.raises(ValueError,match='coverage'):
        ocr.combine_pdf_batches(['one','duplicate'])
    monkeypatch.setattr(ocr,'replay_pdf_batch',lambda path:{**base,'pages':[{'page':int(path)}]})
    assert ocr.combine_pdf_batches(['1','2'])['page_coverage_status']=='complete'


@pytest.mark.parametrize('old,new',[(b'5\t1\t1\t1\t1\t1',b'5\t999\t1\t1\t1\t1'),
    (b'5\t1\t1\t1\t1\t1',b'5\t1\t-1\t1\t1\t1'),
    (b'5\t1\t1\t1\t1\t1',b'5\t1\t1\t1\t1\t0')])
def test_misattributed_tsv_words_are_rejected(old,new):
    with pytest.raises(ValueError,match='hierarchy'):
        ocr.parse_tsv(tsv().replace(old,new),200,100)


def test_frozen_batch_never_silently_repeats_incomplete_ocr(tmp_path,monkeypatch):
    job=tmp_path/'job';job.mkdir(mode=0o700)
    source=tmp_path/'source.pdf';source.write_bytes(b'%PDF synthetic')
    pins={'synthetic':'non-executable'}
    monkeypatch.setattr(ocr,'runtime_pins',lambda:pins)
    request={'contract':ocr.CONTRACT,'source_path':str(source),
        'source_sha256':ocr.sha(source.read_bytes()),'page_numbers':[1],'width':1800,'runtime_pins':pins}
    (job/'request.json').write_text(json.dumps(request))
    monkeypatch.setattr(ocr,'run_private',lambda *a,**kw:pytest.fail('Frozen OCR must not rerun'))
    with pytest.raises((ValueError,FileNotFoundError)):
        ocr.run_pdf_batch(source,job,[1])


@pytest.mark.skipif(platform.system()!='Linux',reason='Real bubblewrap/Tesseract qualification is Linux only')
def test_native_pdf_ocr_replay_tamper_detection_and_private_boundary(tmp_path, monkeypatch):
    from reportlab.pdfgen import canvas
    from delivery.isolation import isolation_available, run_private
    if not isolation_available()[0] or not ocr.BINARY.is_file() or not ocr.LANGUAGE.is_file():
        pytest.skip('Native OCR dependencies absent')
    source=tmp_path/'synthetic.pdf'
    document=canvas.Canvas(str(source),pagesize=(612,792))
    document.setFont('Helvetica',24)
    document.drawString(60,680,'SYNTHETIC OCR CHECK 731')
    document.save()
    job=tmp_path/'private-job';job.mkdir(mode=0o700)
    result=ocr.run_pdf_batch(source,job,[1],width=1800)
    text=' '.join(row['text'] for row in result['pages'][0]['observations'])
    assert 'SYNTHETIC OCR CHECK 731' in text
    assert result['financial_validation']=='not_established'
    assert result['network_access']=='denied'
    assert ocr.replay_pdf_batch(job)==result
    assert ocr.run_pdf_batch(source,job,[1],width=1800)==result
    raw=job/'page_0001.tsv'
    original_tsv=raw.read_bytes()
    raw.write_bytes(original_tsv.replace(b'731',b'999'))
    with pytest.raises(ValueError,match='binding changed'):
        ocr.replay_pdf_batch(job)
    raw.write_bytes(original_tsv)
    result_file,receipt_file=job/'result.json',job/'receipt.json'
    original_result,original_receipt=result_file.read_bytes(),receipt_file.read_bytes()
    forged=json.loads(original_result)
    forged['pages'][0]['height_pixels']*=2
    result_file.write_text(json.dumps(forged))
    forged_receipt=json.loads(original_receipt)
    forged_receipt['result_sha256']=ocr.sha(result_file.read_bytes())
    receipt_file.write_text(json.dumps(forged_receipt))
    with pytest.raises(ValueError,match='geometry invalid'):
        ocr.replay_pdf_batch(job)
    result_file.write_bytes(original_result);receipt_file.write_bytes(original_receipt)
    real_pins=ocr.runtime_pins
    monkeypatch.setattr(ocr,'runtime_pins',lambda:{**real_pins(),'projection':'synthetic-changed-code'})
    with pytest.raises(ValueError,match='runtime provenance changed'):
        ocr.replay_pdf_batch(job)
    monkeypatch.setattr(ocr,'runtime_pins',real_pins)
    canary=tmp_path/'outside-private-ocr.txt';canary.write_text('synthetic-outside-job-canary')
    monkeypatch.setenv('PRIVATE_OCR_SYNTHETIC_SECRET','must-not-cross')
    probe = '''import json,os,socket,pathlib
try:
    pathlib.Path(%r).read_text(); readable=True
except OSError: readable=False
connection=socket.socket(); connection.settimeout(.2)
try:
    connection.connect(('127.0.0.1',11434)); reachable=True
except OSError: reachable=False
finally: connection.close()
print(json.dumps({'secret_present':'PRIVATE_OCR_SYNTHETIC_SECRET' in os.environ,
                 'outside_readable':readable,'model_reachable':reachable}))
''' % str(canary)
    observed=json.loads(run_private([sys.executable,'-I','-c',probe],job,timeout=10))
    assert observed=={'secret_present':False,'outside_readable':False,'model_reachable':False}
