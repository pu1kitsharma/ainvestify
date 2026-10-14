"""Reviewed Claude Code validators preserve exact text and generic label binding."""
import pytest
from agents.research.decision_components import (validate_decision_components,
    validate_financial_label_binding, financial_label_families)


def test_exact_space_join_bounds_keys_floor_and_controls():
    left='  If an unproved delivery condition failed, '+('a'*30)+' '
    right='a prospective adverse consequence could follow '+('b'*30)+'  '
    unit={'failure_condition':left,'prospective_consequence':right}
    assert validate_decision_components('risk',unit,'',90)==left+' '+right
    assert len(validate_decision_components('risk',{'failure_condition':'a'*210,'prospective_consequence':'b'*210},'',421))==421
    for invalid in ('a'*44,'a'*211,' '*60,'a'*30+'\n'+'b'*30,'a'*30+'\u200b'+'b'*30):
        with pytest.raises(ValueError):
            validate_decision_components('risk',{**unit,'failure_condition':invalid},'',90)
    with pytest.raises(ValueError): validate_decision_components('risk',{**unit,'unexpected':'c'*50},'',90)
    with pytest.raises(ValueError): validate_decision_components('diligence',unit,'',90)
    with pytest.raises(ValueError): validate_decision_components('risk',{'failure_condition':'a'*45,'prospective_consequence':'b'*45},'',180)
    for floor in (True,0,-1,'90',None):
        with pytest.raises(ValueError): validate_decision_components('risk',unit,'',floor)


def test_generic_profit_inflections_financial_metrics_and_nonprofit_boundaries():
    for word in ('profit','profits','profitable','profitability'):
        assert financial_label_families(word)=={'profit'}
        validate_financial_label_binding(word,'The source explicitly labels profit.')
        with pytest.raises(ValueError,match='profit'):
            validate_financial_label_binding(word,'A source description of partner distribution.')
    assert financial_label_families('nonprofit Non-Profit cashew marginal profiteer')==set()
    assert financial_label_families('premium GWP EBITDA sales ARPU GMV expenses')=={'premium','gwp','ebitda','sales','arpu','gmv','expense'}
    with pytest.raises(ValueError,match='earnings'): validate_financial_label_binding('earnings','Partner distribution service')
    unit={'failure_condition':'If the reported delivery condition failed to support profitability,',
          'prospective_consequence':'a prospective adverse outcome could undermine the investment case.'}
    with pytest.raises(ValueError,match='profit'): validate_decision_components('risk',unit,'Partner distribution description',90)
