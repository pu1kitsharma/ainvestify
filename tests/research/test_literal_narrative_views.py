"""Narrative views retrieve exact text, excluding diagrams and numeric rows."""
import pytest

from agents.research.investment_memo import Source
from agents.research.literal_narrative_views import literal_narrative_views


def source(text):
    return Source(id='S1',url='https://example.test/source',title='Synthetic source',version='v'*64,
                  attribution='Synthetic unverified company report',passage=text)


@pytest.mark.parametrize('delimiter',['\n','\\n'])
def test_exact_offsets_narrative_continuations_and_entity_category_table_exclusion(delimiter):
    text=delimiter.join(['Verticalized providers','Infra Building Insurtechs Traditional Brokers','Alpha Company','Beta Company',
        'We build scalable software for distribution','through local operating partnerships',
        'Infra Building Insurtechs Traditional Brokers','Category Two','Gamma Corporation','No direct competitors are claimed by the company',
        'Delta Company, Epsilon Corporation','Potential USD Mn','Revenue 1.23 5.67',
        'Grow 1.23 5.67','Limited overlap with incumbent product offerings',
        'First-mover distribution proposition is a company description'])
    original=source(text); rows=literal_narrative_views(original)
    assert 1<=len(rows)<=6
    offered=' '.join(row['exact_text'] for row in rows.values())
    assert 'We build scalable software' in offered
    assert 'through local operating partnerships' in offered
    assert 'No direct competitors' in offered
    assert 'Limited overlap' in offered
    assert 'First-mover' in offered
    for excluded in ('Infra Building Insurtechs Traditional Brokers','Alpha Company','Beta Company','Category Two','Gamma Corporation',
        'Delta Company','Epsilon Corporation','Potential USD','1.23','5.67'):
        assert excluded not in offered
    for eid,row in rows.items():
        assert eid.startswith('S1.n') and row['source_id']=='S1'
        assert row['exact_text']==text[row['start']:row['end']]
        assert 15<=len(row['exact_text'])<=600
        assert len(row['exact_text'].split(delimiter))<=4
    assert original.passage==text and '1.23 5.67' in original.passage


def test_no_fallback_for_bare_lists_or_numeric_rows_and_bounded_fragment_count():
    for text in ('Category A\nAlpha Company\nBeta Corporation\nCategory B\nGamma Company\nInfra Building Insurtechs Traditional Brokers',
                 'Revenue USD Mn\n2024 0.34 0.93\n2025 1.23 5.67\nGrow 0.34 0.93'):
        with pytest.raises(ValueError,match='no bounded literal narrative view'):
            literal_narrative_views(source(text))
    text='\n'.join('We provide an operating product through local partners\nCategory X' for _ in range(10))
    assert len(literal_narrative_views(source(text)))==6
    long='We build '+('scalable services through partners '*30)
    row=next(iter(literal_narrative_views(source(long)).values()))
    assert len(row['exact_text'])<=600 and row['exact_text']==long[row['start']:row['end']]
