"""Real OS boundary probes; run explicitly outside a nested tool sandbox."""
import json
import os
from pathlib import Path
import socket
import sys
import pytest
from delivery.isolation import run_private

pytestmark=pytest.mark.skipif(os.environ.get('RUN_PRIVATE_RUNTIME_TESTS')!='1',
    reason='Requires real macOS sandbox execution; run the explicit qualification command')


def test_network_sibling_file_and_secrets_are_unavailable(tmp_path,monkeypatch):
    job=tmp_path/'job';job.mkdir();secret=tmp_path/'other-room.txt';secret.write_text('synthetic-private-canary')
    monkeypatch.setenv('SYNTHETIC_SECRET_KEY','must-not-reach-worker')
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
    code='''
import json,os,socket
from pathlib import Path
result={}
try:
    Path(%r).read_text();result['file_denied']=False
except PermissionError:result['file_denied']=True
try:
    socket.create_connection(('127.0.0.1',%d),timeout=1);result['network_denied']=False
except PermissionError:result['network_denied']=True
result['secret_absent']='SYNTHETIC_SECRET_KEY' not in os.environ
print(json.dumps(result))
'''%(str(secret),listener.getsockname()[1])
    try:result=json.loads(run_private([sys.executable,'-c',code],job))
    finally:listener.close()
    assert result=={'file_denied':True,'network_denied':True,'secret_absent':True}


def test_isolated_parser_and_renderer_produce_real_files(tmp_path):
    from io import BytesIO
    from openpyxl import Workbook
    from delivery.inspection import inspect_bytes
    job=tmp_path/'job';job.mkdir()
    script=Path(__file__).resolve().parents[2]/'scripts/private_document_worker.py'
    workbook=Workbook();workbook.active['A1']='=1+2';buffer=BytesIO();workbook.save(buffer)
    (job/'input.bin').write_bytes(buffer.getvalue())
    (job/'request.json').write_text(json.dumps({'operation':'inspect','format':'xlsx'}))
    run_private([sys.executable,script],job)
    assert json.loads((job/'result.json').read_text())['formula_count']==1
    (job/'request.json').write_text(json.dumps({'operation':'render','title':'Synthetic qualification',
        'memo_sections':[['Synthetic fixture','Illustrative test content only','Synthetic source fixture']],
        'intro_sections':[['Synthetic fixture','Illustrative test content only','Synthetic source fixture','statement']],
        'pitch_sections':[['Synthetic evidence','Illustrative test content only','Synthetic source fixture','evidence']]}))
    run_private([sys.executable,script],job)
    for name,fmt in [('intro.pptx','pptx'),('intro.pdf','pdf'),
                     ('pitch.pptx','pptx'),('pitch.pdf','pdf'),
                     ('memo.docx','docx'),('memo.pdf','pdf'),
                     ('research.pdf','pdf')]:
        assert inspect_bytes((job/name).read_bytes(),fmt)['structural_status']=='pass'


@pytest.mark.parametrize('mode',[{'local_ipc':True},{'local_model':True}])
def test_worker_network_exceptions_do_not_allow_arbitrary_ports(tmp_path,mode):
    job=tmp_path/'job';job.mkdir()
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
    code='import socket\ntry:\n socket.create_connection(("127.0.0.1",%d),timeout=1); print("LEAK")\nexcept PermissionError: print("DENIED")'%listener.getsockname()[1]
    try:assert run_private([sys.executable,'-c',code],job,**mode).strip()==b'DENIED'
    finally:listener.close()


from tests.api.test_authentication import secured, sign_in


def test_isolated_model_snapshot_can_abstain_without_model_calls(secured,tmp_path,monkeypatch):
    from delivery.preparation import prepare_snapshot
    from delivery.jobs import claim
    from store import Store
    client,db,users=secured
    monkeypatch.setenv('PRIVATE_ARTIFACT_ROOT',str(tmp_path/'private'))
    sign_in(client,users[0])
    created=client.post('/api/rooms',json={'name':'Synthetic fixture','website':'https://synthetic.example','mandate_type':'fundraising_advisory','terms_summary':'Synthetic engagement terms'}).json()
    with Store(db) as store:
        job=claim(store.conn)
        room=store.get_workspace(users[0][1],workspace_id=created['workspace_id'])
        result=prepare_snapshot(store,job,room,timeout=30)
    assert isinstance(result['analyst_pack'],dict)
    assert list((tmp_path/'private').rglob('snapshot.db'))
    assert not result['analyst_pack'].get('sections')



def test_renderer_font_is_readable_but_adjacent_application_and_private_data_are_not(tmp_path):
    from delivery.isolation import READONLY_RENDER_FONTS
    font=READONLY_RENDER_FONTS[0]
    if not font.is_file():pytest.skip('Qualified runtime font is not installed')
    adjacent=font.parent/'DejaVuSerif.ttf'
    if not adjacent.is_file():adjacent=font.parents[3]/'Info.plist'
    assert adjacent.is_file()
    job=tmp_path/'job';job.mkdir()
    private=tmp_path/'other-room.txt';private.write_text('synthetic-private-canary')
    code="""
import json,os
from pathlib import Path
font=Path(%r)
result={'font_read':len(font.read_bytes())>1000}
for key,path in [('adjacent_denied',Path(%r)),('private_denied',Path(%r))]:
 try:path.read_bytes();result[key]=False
 except PermissionError:result[key]=True
try:
 fd=os.open(font,os.O_WRONLY);os.close(fd);result['font_write_denied']=False
except PermissionError:result['font_write_denied']=True
print(json.dumps(result))
"""%(str(font),str(adjacent),str(private))
    assert json.loads(run_private([sys.executable,'-c',code],job))=={
        'font_read':True,'adjacent_denied':True,'private_denied':True,'font_write_denied':True}
