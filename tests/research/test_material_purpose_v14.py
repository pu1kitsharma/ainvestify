"""Source-first purpose slots: v14 keeps sentences and headings distinct within a deck."""
import json

import pytest

from agents.inference.model_authorship import recorded_call
from agents.research.investment_memo import renderable_sections
from agents.research.material_purpose_draft import memo_sentence_candidates
from agents.research.material_slides import replay_material_rows
from tests.research.test_memo_section_projection import SOURCES, accepted_v2


def fixture():
    result, attempts, output = accepted_v2()
    sections = renderable_sections(result, SOURCES, attempts, projection='reader_v2')
    claim = output['diligence_plan']['claims'][0]
    financial = {'unknowns': [{'id': 'u' * 64, 'question': 'What revenue and cost belong to the pilot?',
                               'evidence_needed': 'Reviewed accounts for the pilot period.'}],
                 'claims': [{'id': 'c' * 64, 'source_id': claim['source_id'],
                             'assertion': claim['assertion']}]}
    base = {'input_revision': 'r' * 64, 'source_hash': 's' * 64, 'memo_digest': 'm' * 64,
            'sections': sections, 'financial_unknown_candidates': financial,
            'memo_sentence_candidates': memo_sentence_candidates(result['accepted']
                                                                  if 'accepted' in result else result)}
    return sections, base


class Selector:
    name = 'synthetic-local'

    def __init__(self, heading=lambda slot: f'Topic {slot}'):
        self.heading, self.last_response_text, self.last_route = heading, '', {}
        self.first = None

    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        payload = json.loads(evidence)
        slot = payload['slot']
        if slot == 'financial_unknown':
            answer = {'heading': self.heading(slot), 'unknown_id': 'u' * 64,
                      'claim_id': 'c' * 64, 'status': 'unverified', 'layout': 'statement'}
        else:
            ids = sorted(row['id'] for row in payload['candidates'])
            # Reuse the first selection wherever the slot still offers it.
            pick = self.first if self.first in ids else ids[0]
            self.first = self.first or pick
            answer = {'heading': self.heading(slot), 'sentence_ids': [pick],
                      'layout': 'statement'}
        self.last_response_text = json.dumps(answer)
        self.last_route = {'model': self.name}
        return schema.model_validate(answer)


def drive(version, kind='intro_deck', selector=None):
    sections, base = fixture()
    attempts, selector = [], selector or Selector()
    payload = {'kind': kind, **base}
    for _ in range(12):
        state = replay_material_rows(kind, payload, attempts, sections,
                                     model_name='synthetic-local', contract_version=version)
        if state['state'] != 'needs_call':
            return state, attempts
        recorded_call(selector, state['task'], state['instruction'], state['payload'],
                      state['schema'], attempts, lambda: None)
    raise AssertionError('deck did not finish within its slot count')


def selected_ids(attempts):
    return [sentence for row in attempts
            for sentence in json.loads(row['raw_response']).get('sentence_ids', [])]


def test_v13_still_replays_and_may_repeat_a_sentence_across_slots():
    state, attempts = drive('purpose_v13')
    assert state['state'] == 'accepted'
    assert len(selected_ids(attempts)) > len(set(selected_ids(attempts)))


def test_v14_offers_each_slot_only_unused_sentences_and_finishes_distinct():
    state, attempts = drive('purpose_v14')
    assert state['state'] == 'accepted'
    ids = selected_ids(attempts)
    assert len(ids) == len(set(ids))
    later = attempts[1]['input']
    assert later['candidate_contract'] == 'purpose-v14-distinct-memo-sentences-v1'
    assert later['used_sentence_ids'] == json.loads(attempts[0]['raw_response'])['sentence_ids']
    assert not set(later['used_sentence_ids']) & {row['id'] for row in later['candidates']}
    assert later['used_headings'] == ['topic company']


def test_v14_blocks_a_repeated_deck_heading_instead_of_accepting_it():
    state, _ = drive('purpose_v14', selector=Selector(lambda slot: 'Market position'))
    assert state['state'] == 'blocked' and 'repeats an earlier heading' in state['reason']


def test_v14_replay_rejects_saved_v13_responses():
    _, attempts = drive('purpose_v13')
    sections, base = fixture()
    with pytest.raises(ValueError, match='Saved source-first slide response changed'):
        replay_material_rows('intro_deck', {'kind': 'intro_deck', **base}, attempts, sections,
                             model_name='synthetic-local', contract_version='purpose_v14')
