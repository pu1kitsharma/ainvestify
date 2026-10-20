"""Independently score exact model-authored workbook cells; never repair them."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from io import BytesIO
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from openpyxl import load_workbook
from agents.tools.contracts import bounded_package
from agents.tools.workbook import WorkbookTools
from agents.tools.financial_audit import audit_financial_artifacts


def audit_outputs(root, expectations, *, mapping='mapping-authored.json', workbook='model.xlsx', memo=None):
    root=Path(root).resolve(strict=True)
    def read(name):
        path=(root/name).resolve(strict=True)
        if not path.is_relative_to(root):raise ValueError('Artifact escapes evaluation sandbox')
        with path.open('rb') as stream:content=stream.read(20_000_001)
        if not 0<len(content)<=20_000_000:raise ValueError('Artifact byte bound')
        return content
    mapping_bytes,content=read(mapping),read(workbook)
    spec=json.loads(mapping_bytes)
    bounded_package(content,max_bytes=20_000_000,max_cells=10000)
    book=load_workbook(BytesIO(content),data_only=False,keep_links=False)
    evaluator=WorkbookTools.__new__(WorkbookTools)
    evaluator.root,evaluator.book,evaluator.max_cells=root,book,10000
    calculation=WorkbookTools.recalc.__wrapped__(evaluator)
    computed={(r['sheet'],r['cell']):r['value'] for r in calculation['values']}
    checks=[]
    for expected in expectations['expected_outputs']:
        ref=spec.get('metrics',{}).get(expected['id'])
        row={'id':expected['id'],'status':'mapping_missing'}
        if ref:
            try:
                cell=book[ref['sheet']][ref['cell']]
                value=computed.get((ref['sheet'],ref['cell'])) if cell.data_type=='f' else cell.value
                numeric=type(value) in (int,float) and math.isfinite(value) and abs(value-expected['value'])<=expected['tolerance']
                formula=not expected.get('require_formula') or cell.data_type=='f'
                unit=ref['unit']==expected['unit']
                row.update(actual=value,expected=expected['value'],value_match=numeric,
                    formula_requirement_match=formula,unit_match=unit,
                    status='matched' if numeric and formula and unit else 'failed')
            except (KeyError,ValueError,TypeError):row['status']='invalid_mapping'
        checks.append(row)
    report={'contract':'model-workbook-objective-audit/v1','scope':'mapped_numeric_outputs_only',
            'matched':sum(r['status']=='matched' for r in checks),'required':len(checks),'checks':checks,
            'calculation_findings':calculation['findings'],'release':'blocked','full_banker':False,
            'metadata_and_source_semantics':'not_assessed_by_numeric_check','office_recalculation':'not_run',
            'hashes':{'workbook':hashlib.sha256(content).hexdigest(),'mapping':hashlib.sha256(mapping_bytes).hexdigest(),
                      'expectations':hashlib.sha256(json.dumps(expectations,sort_keys=True).encode()).hexdigest()}}
    report['status']='numeric_checks_passed' if checks and report['matched']==len(checks) and not calculation['findings'] else 'failed'
    if memo:
        full_spec=json.loads(read('output_spec.json'))
        report['full_artifact_audit']=audit_financial_artifacts(root,workbook=workbook,memo=memo,
            output_spec=full_spec,expectations=expectations,sources=['case.json'])
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--expectations',type=Path,required=True,help='Independent key; never passed to inference')
    parser.add_argument('--mapping',default='mapping-authored.json')
    parser.add_argument('--memo')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=audit_outputs(args.root,json.loads(args.expectations.read_text()),mapping=args.mapping,memo=args.memo)
    with args.output.open('x') as stream:json.dump(report,stream,indent=2)
    print(json.dumps({k:report[k] for k in ('status','matched','required','release')}))
    return 0 if report['status']=='numeric_checks_passed' else 1


if __name__=='__main__':raise SystemExit(main())
