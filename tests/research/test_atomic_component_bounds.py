"""Quantified premises cannot leak into fresh hypothetical prose."""
import pytest

from agents.research.atomic_component_bounds import (
    leak_hits, validate_unquantified_component)


@pytest.mark.parametrize('fact', [
    '6.75', '3.5k', '45%', '2.7Bn', '₹500', '$3m', 'FY2026',
    'Q3', '2026-10-10', 'next year', 'October', 'three million',
    '６．７５', 'USD500', 'INR800', 'EUR3.5k', 'usd500', 'october',
])
def test_hypothetical_quantification_is_rejected_without_rewriting(fact):
    text = 'If demand includes ' + fact + ', the plan could work.'
    before = text
    assert leak_hits(text)
    with pytest.raises(ValueError, match='source premise'):
        validate_unquantified_component(text)
    assert text == before


@pytest.mark.parametrize('name', ['B2B', 'Web3', 'GPT4', 'M365', 'R2D2'])
def test_alphanumeric_names_are_not_silently_reinterpreted_as_numbers(name):
    text = 'If ' + name + ' integration works, delivery could improve.'
    assert not leak_hits(text)
    assert validate_unquantified_component(text) == text


def test_guard_does_not_approve_unquantified_financial_comparison():
    # This must still fail the separate exact-source and semantic reviewer gates.
    text = 'If higher margins persist, delivery could improve.'
    assert validate_unquantified_component(text) == text


@pytest.mark.parametrize('text', [None, 4, '', '   '])
def test_no_synthetic_component_is_created_for_invalid_text(text):
    with pytest.raises(ValueError, match='nonempty'):
        validate_unquantified_component(text)
