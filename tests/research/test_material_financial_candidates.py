"""Financial topic fallback retains exact model text and successful legacy packets."""
import copy
import json

import pytest

from agents.inference.model_authorship import digest
from agents.research.material_purpose_draft import financial_unknown_candidates, _schema_v12_financial, _v12_financial_slide

FIELDS=('investment_thesis','business_and_market','differentiation_and_execution','risks_and_countercase','diligence_plan')


def memo(question,needed,assertion):
    out={'unknowns':[{'question':question,'evidence_needed':needed}],
         'recommendation_claims':[{'source_id':'S2','assertion':assertion}]}
    out.update({field:{'claims':[]} for field in FIELDS})
    return out


def test_successful_legacy_packet_is_exact_even_with_new_financial_aliases():
    original=memo('Which revenue results are independently reviewed?','Audited accounts supporting reported results.',
        'The source reports revenue as a company target rather than independently verified results.')
    baseline=financial_unknown_candidates(original)
    changed=copy.deepcopy(original)
    changed['unknowns'].append({'question':'What GWP is supported by the operating model?','evidence_needed':'Reviewed premium reconciliations and statements.'})
    changed['recommendation_claims'].append({'source_id':'S3','assertion':'The source reports an ARR target, not achieved operating capital.'})
    assert json.dumps(financial_unknown_candidates(changed))==json.dumps(baseline)


@pytest.mark.parametrize('term',['ARR','GWP','EBITDA','cash availability','operating capital','capital efficiency'])
def test_empty_side_fallback_keeps_verbatim_assertion_source_and_diligence_question(term):
    question='What documentation supports the reported '+term+'?'
    needed='Reviewed company records reconciling the reported '+term+'.'
    assertion='The source reports '+term+' as a company description that requires independent verification.'
    original=memo(question,needed,assertion); saved=copy.deepcopy(original)
    packet=financial_unknown_candidates(original)
    assert packet=={'unknowns':[{'id':digest({'question':question,'evidence_needed':needed}),'question':question,'evidence_needed':needed}],
        'claims':[{'id':digest({'source_id':'S2','assertion':assertion}),'source_id':'S2','assertion':assertion}]}
    assert original==saved
    item=_schema_v12_financial(packet).model_validate({'heading':'Financial evidence','unknown_id':packet['unknowns'][0]['id'],
        'claim_id':packet['claims'][0]['id'],'status':'unverified','layout':'evidence'})
    slide=_v12_financial_slide(item,packet,[('Source report',assertion+' [S2].','[S2] Synthetic retained source')])
    assert slide.body.startswith(assertion.rstrip('.')+' [S2].')
    assert 'Open diligence question: '+question in slide.body
    assert 'Evidence requested: '+needed in slide.body
    assert slide.body.count('[S2]')==1
    assert 'source omits' not in slide.body


def test_fallback_does_not_enroll_unrelated_product_claim_or_add_numeric_unknowns():
    unrelated=memo('What product interfaces are documented?','Architecture records for the reported software interfaces.',
        'The company reports that its software interfaces support an operating product workflow.')
    with pytest.raises(ValueError): financial_unknown_candidates(unrelated)
    bounded=memo('What ARR applies in 2024?','Operating model records for ARR.',
        'The source reports ARR as a company target requiring independent verification.')
    with pytest.raises(ValueError): financial_unknown_candidates(bounded)
