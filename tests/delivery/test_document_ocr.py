"""Private source transcription cannot become unaudited financial facts."""
from copy import deepcopy
from io import BytesIO
import hashlib
import json

import pytest
from PIL import Image
from reportlab.pdfgen import canvas

from delivery import document_ocr as ocr


def inputs(tmp_path):
    image = tmp_path / 'page.png'
    Image.new('RGB', (80, 80), 'white').save(image)
    sha = hashlib.sha256(image.read_bytes()).hexdigest()
    request = {'contract': ocr.CONTRACT, 'images': [{'id': 'page_1', 'path': str(image), 'sha256': sha}]}
    result = {'contract': ocr.CONTRACT, 'language_correction': False,
        'engine': 'AppleVision-VNRecognizeTextRequest', 'coordinate_system': 'normalized-bottom-left',
        'images': [{'id': 'page_1', 'image_sha256': sha,
                    'observations': [{'text': 'Projected USD million 12', 'confidence': .91,
                                      'bbox': [.1, .2, .6, .1]}]}]}
    return request, result


def test_complete_literal_ocr_binding_cannot_be_reused_for_changed_source_image(tmp_path):
    request, result = inputs(tmp_path)
    assert ocr.checked_ocr_result(request, result) == result
    Image.new('RGB', (80, 80), 'black').save(request['images'][0]['path'])
    with pytest.raises(ValueError, match='image binding changed'):
        ocr.checked_ocr_result(request, result)


@pytest.mark.parametrize('change', ['missing_page', 'bad_confidence', 'outside_geometry', 'autocorrected'])
def test_incomplete_or_invalid_transcription_is_not_a_valid_ocr_receipt(tmp_path, change):
    request, result = inputs(tmp_path)
    if change == 'missing_page': result['images'] = []
    elif change == 'bad_confidence': result['images'][0]['observations'][0]['confidence'] = float('nan')
    elif change == 'outside_geometry': result['images'][0]['observations'][0]['bbox'] = [.8, .2, .6, .1]
    else: result['language_correction'] = True
    with pytest.raises(ValueError):ocr.checked_ocr_result(request, result)


def test_private_image_escape_rejected_before_any_recognition_or_compiler(tmp_path, monkeypatch):
    request, _ = inputs(tmp_path)
    job = tmp_path / 'job'; job.mkdir(mode=0o700)
    monkeypatch.setattr(ocr, 'checked_local_ocr_worker', lambda: pytest.fail('Do not compile or recognise an outside image'))
    with pytest.raises(ValueError, match='belong to the private job'):
        ocr.recognize_images([{'id': 'page_1', 'path': request['images'][0]['path']}], job)
    assert not (job / 'ocr_request.json').exists()


def test_reopened_record_requires_exact_receipt_and_never_repeats_ocr(tmp_path, monkeypatch):
    request, result = inputs(tmp_path)
    binary=tmp_path / 'private-vision-ocr'
    binary.write_bytes(b'generic-code'); binary.chmod(0o700)
    binary_sha=hashlib.sha256(binary.read_bytes()).hexdigest()
    (tmp_path / 'build_receipt.json').write_text(json.dumps({'binary_sha256':binary_sha}))
    monkeypatch.setattr(ocr, 'checked_local_ocr_worker', lambda:binary)
    request.update(languages=['en-US'], worker_source_sha256=hashlib.sha256(ocr.SOURCE.read_bytes()).hexdigest(),
                   worker_binary_sha256=binary_sha)
    frozen, output = tmp_path / 'ocr_request.json', tmp_path / 'ocr_result.json'
    frozen.write_text(json.dumps(request)); output.write_text(json.dumps(result))
    receipt = {'request_sha256': hashlib.sha256(frozen.read_bytes()).hexdigest(),
               'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
               'worker_source_sha256': request['worker_source_sha256'],
               'worker_binary_sha256':binary_sha}
    (tmp_path / 'ocr_receipt.json').write_text(json.dumps(receipt))
    monkeypatch.setattr(ocr, 'run_private', lambda *args, **kwargs: pytest.fail('Unchanged OCR must replay'))
    images = [{'id': 'page_1', 'path': request['images'][0]['path']}]
    assert ocr.recognize_images(images, tmp_path) == result
    changed = deepcopy(result); changed['images'][0]['observations'][0]['text'] = 'Actual USD million 12'
    output.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match='receipt changed'):
        ocr.recognize_images(images, tmp_path)


def test_complete_page_rasters_retained_and_excess_pages_are_not_silently_cropped(tmp_path):
    stream = BytesIO(); doc = canvas.Canvas(stream)
    doc.drawString(20, 700, 'Source-reported draft'); doc.showPage()
    doc.rect(30, 100, 80, 60); doc.showPage(); doc.save()
    content = stream.getvalue()
    with pytest.raises(ValueError, match='page count'):
        ocr.rasterize_pdf(content, tmp_path, max_pages=1)
    images = ocr.rasterize_pdf(content, tmp_path, width=800)
    assert [row['page'] for row in images] == [1, 2]
    assert all((tmp_path / ('page_%04d.png' % row['page'])).is_file() for row in images)
    with pytest.raises(ValueError, match='already exists'):
        ocr.rasterize_pdf(content, tmp_path, width=800)


def test_native_worker_runs_checked_copy_inside_job_without_expanding_read_capabilities(tmp_path, monkeypatch):
    job=tmp_path/'private-job'
    job.mkdir(mode=0o700)
    image=job/'input.png'
    Image.new('RGB',(100,100),'white').save(image)
    build=tmp_path/'generic-build'
    build.mkdir(mode=0o700)
    binary=build/'private-vision-ocr'
    binary.write_bytes(b'generic-provenance-checked-code')
    binary.chmod(0o700)
    (build/'build_receipt.json').write_text(json.dumps({'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()}))
    monkeypatch.setattr(ocr,'checked_local_ocr_worker',lambda:binary)
    calls=[]
    def isolated(command, directory, **kwargs):
        calls.append((command,directory,kwargs))
        executable=command[0]
        assert executable.parent==job
        assert executable.read_bytes()==binary.read_bytes()
        assert executable.stat().st_mode & 0o777==0o700
        assert kwargs=={'timeout':110}
        request=json.loads(command[1].read_text())
        output={'contract':ocr.CONTRACT,'engine':'AppleVision-VNRecognizeTextRequest',
                'language_correction':False,'coordinate_system':'normalized-bottom-left',
                'images':[{'id':request['images'][0]['id'],
                           'image_sha256':request['images'][0]['sha256'],
                           'observations':[{'text':'Synthetic source 123','confidence':1.0,
                                            'bbox':[0.1,0.1,0.4,0.1]}]}]}
        command[2].write_text(json.dumps(output))
    monkeypatch.setattr(ocr,'run_private',isolated)
    result=ocr.recognize_images([{'id':'test_01','path':image}],job)
    assert result['images'][0]['observations'][0]['text']=='Synthetic source 123'
    receipt=json.loads((job/'ocr_receipt.json').read_text())
    assert receipt['worker_binary_sha256']==hashlib.sha256(binary.read_bytes()).hexdigest()
    assert receipt['network_access']=='denied'
    assert receipt['financial_validation']=='not_established'
    assert len(calls)==1
    request=json.loads((job/'ocr_request.json').read_text())
    assert request['worker_binary_sha256']==receipt['worker_binary_sha256']
    assert ocr.recognize_images([{'id':'test_01','path':image}],job)==result
    assert len(calls)==1
    (job/'private-vision-ocr').write_bytes(b'changed-private-executable')
    with pytest.raises(ValueError,match='executable copy changed'):
        ocr.recognize_images([{'id':'test_01','path':image}],job)
    assert len(calls)==1


def retained_document_ocr(tmp_path,monkeypatch):
    """Recorded synthetic evidence fixture, never recognition or model output."""
    import math
    job=tmp_path/'recorded-ocr'
    job.mkdir(mode=0o700)
    stream=BytesIO()
    pdf=canvas.Canvas(stream,pagesize=(612,792))
    for _ in range(2):
        pdf.drawString(30,700,'Synthetic source label 123')
        pdf.showPage()
    pdf.save()
    source=stream.getvalue()
    source_sha=hashlib.sha256(source).hexdigest()
    (job/'source.pdf').write_bytes(source)
    source_request={'contract':ocr.CONTRACT,'source_sha256':source_sha,'width':800,
                    'max_pages':120,'languages':['en-US']}
    (job/'request.json').write_text(json.dumps(source_request))
    images=[]
    requested=[]
    outputs=[]
    for number in range(1,3):
        ident='page_%04d'%number
        path=job/(ident+'.png')
        Image.new('RGB',(800,math.ceil(792*800/612)),'white').save(path)
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        images.append({'id':ident,'path':str(path),'page':number,
                       'width_points':612.0,'height_points':792.0})
        requested.append({'id':ident,'path':str(path),'sha256':sha})
        outputs.append({'id':ident,'image_sha256':sha,'observations':[
            {'text':'Synthetic source label 123','confidence':1.0,'bbox':[.1,.1,.6,.1]}]})
    raster={'contract':ocr.CONTRACT,'source_sha256':source_sha,'images':images,'elapsed_seconds':0.1}
    (job/'page_images.json').write_text(json.dumps(raster))
    source_pin=hashlib.sha256(ocr.SOURCE.read_bytes()).hexdigest()
    binary_bytes=b'generic immutable synthetic executable fixture'
    binary_pin=hashlib.sha256(binary_bytes).hexdigest()
    build_root=tmp_path/'generic-builds'
    build=build_root/(source_pin+'-explicit-sdk-v1')
    build.mkdir(mode=0o700,parents=True)
    (build/'private-vision-ocr').write_bytes(binary_bytes)
    (build/'build_receipt.json').write_text(json.dumps({
        'contract':'private-vision-ocr-build-v1','source_sha256':source_pin,
        'binary_sha256':binary_pin,'compiler':str(ocr.SWIFTC),'sdk':str(ocr.SDK),
        'private_inputs':False}))
    monkeypatch.setattr(ocr,'BUILD_ROOT',build_root)
    (job/'private-vision-ocr').write_bytes(binary_bytes)
    request={'contract':ocr.CONTRACT,'images':requested,'languages':['en-US'],
             'worker_source_sha256':source_pin,'worker_binary_sha256':binary_pin}
    result={'contract':ocr.CONTRACT,'engine':'AppleVision-VNRecognizeTextRequest',
            'language_correction':False,'coordinate_system':'normalized-bottom-left','images':outputs}
    (job/'ocr_request.json').write_text(json.dumps(request))
    (job/'ocr_result.json').write_text(json.dumps(result))
    receipt={'contract':ocr.CONTRACT,
             'request_sha256':hashlib.sha256((job/'ocr_request.json').read_bytes()).hexdigest(),
             'output_sha256':hashlib.sha256((job/'ocr_result.json').read_bytes()).hexdigest(),
             'worker_source_sha256':source_pin,'worker_binary_sha256':binary_pin,
             'elapsed_seconds':0.2,'image_count':2,'network_access':'denied',
             'recognition_status':'source_transcription_unreviewed','financial_validation':'not_established'}
    (job/'ocr_receipt.json').write_text(json.dumps(receipt))
    pages=[{**row,'page':image['page'],'source_sha256':source_sha,
            'engine':result['engine'],'language_correction':False,
            'coordinate_system':'normalized-bottom-left','width_points':image['width_points'],
            'height_points':image['height_points']} for image,row in zip(images,outputs)]
    projection={'contract':ocr.CONTRACT,'source_sha256':source_sha,'pages':pages,
                'source_transcription_status':'local_ocr_proposed_unreviewed','financial_validation':'not_established'}
    (job/'page_observations.json').write_text(json.dumps(projection))
    for name in ('recognize_images','run_private','build_local_ocr_worker','rasterize_pdf'):
        monkeypatch.setattr(ocr,name,lambda *args,**kwargs:pytest.fail('Read-only replay must not execute recognition/compiler/rendering'))
    return job,projection


def test_document_ocr_replay_is_read_only_and_reconstructs_complete_raw_projection(tmp_path,monkeypatch):
    job,projection=retained_document_ocr(tmp_path,monkeypatch)
    before={path.name:path.read_bytes() for path in job.iterdir()}
    assert ocr.replay_document_ocr(job)==projection
    assert {path.name:path.read_bytes() for path in job.iterdir()}==before


@pytest.mark.parametrize('change',[ 'projection_text','projection_scope','raster_geometry',
    'missing_original_page','swapped_raster_order','escaped_raster','linked_projection',
    'raw_response','receipt_network','copied_binary','original_source'])
def test_document_ocr_replay_blocks_changed_projection_or_source_proof(tmp_path,monkeypatch,change):
    job,_=retained_document_ocr(tmp_path,monkeypatch)
    def mutate(file,fn):
        path=job/file
        value=json.loads(path.read_text())
        fn(value)
        path.write_text(json.dumps(value))
    if change=='projection_text':
        mutate('page_observations.json',lambda v:v['pages'][0]['observations'][0].update(text='Manually substituted number 999'))
        # A rewritten derivative hash cannot replace raw OCR/receipt proof.
        projection_sha=hashlib.sha256((job/'page_observations.json').read_bytes()).hexdigest()
        (job/'derived_manifest.json').write_text(json.dumps({'rewritten_projection_sha256':projection_sha}))
    elif change=='projection_scope':
        mutate('page_observations.json',lambda v:v.update(financial_validation='qualified'))
    elif change=='raster_geometry':
        mutate('page_images.json',lambda v:v['images'][0].update(width_points=800.0))
        mutate('page_observations.json',lambda v:v['pages'][0].update(width_points=800.0))
    elif change=='missing_original_page':
        mutate('page_images.json',lambda v:v['images'].pop())
    elif change=='swapped_raster_order':
        mutate('page_images.json',lambda v:v['images'].reverse())
    elif change=='escaped_raster':
        outside=tmp_path/'outside.png'
        outside.write_bytes((job/'page_0001.png').read_bytes())
        mutate('page_images.json',lambda v:v['images'][0].update(path=str(outside)))
    elif change=='linked_projection':
        outside=tmp_path/'outside.json'
        outside.write_bytes((job/'page_observations.json').read_bytes())
        (job/'page_observations.json').unlink()
        (job/'page_observations.json').symlink_to(outside)
    elif change=='raw_response':
        mutate('ocr_result.json',lambda v:v['images'][0]['observations'][0].update(text='Changed raw OCR'))
    elif change=='receipt_network':
        mutate('ocr_receipt.json',lambda v:v.update(network_access='allowed'))
    elif change=='copied_binary':
        (job/'private-vision-ocr').write_bytes(b'changed executable')
    else:
        (job/'source.pdf').write_bytes((job/'source.pdf').read_bytes()+b'changed')
    with pytest.raises(ValueError):
        ocr.replay_document_ocr(job)
