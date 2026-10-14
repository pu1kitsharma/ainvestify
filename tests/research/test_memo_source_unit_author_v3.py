"""Versioned reporting discipline preserves isolated v2 recorded replay."""
import json
from types import SimpleNamespace

from agents.preparation.preparation_budget import PreparationBudget
from agents.research import memo_source_unit_author as author
from tests.research.test_memo_source_unit_author import fixture, PIN
from tests.research.test_memo_source_unit_author_v2 import Model as V2Model, advance


class Model(V2Model):
    def generate_for_task(self, task, instruction, evidence, schema, *, attempt=0):
        assert task == author.TASK_V3 and instruction == author.INSTRUCTION_V3
        payload = json.loads(evidence)
        assert payload['contract'] == author.CONTRACT_V3
        self.calls += 1
        if payload['unit_id'].startswith('r_'):
            obj = {'recommendation': 'defer_pending_evidence',
                'supporting_evidence_id': next(iter(payload['sources'][payload['unit_source_ids'][0]]['spans'])),
                'reported_scope': 'current_description',
                'standalone_text': 'The registry source reports uncertain completion status and current cash availability; dated records would help inform further diligence.'}
        else:
            obj = {'question': 'What operating cash is currently available to the company?',
                'conditional_importance': 'If reviewed cash records were available, they would help assess operating runway.',
                'requested_records': 'Reviewed bank and account records showing current operating cash availability.',
                'requested_time_basis': 'current'}
        self.last_response_text = json.dumps(obj)
        self.last_route = {'model': self.name, **author.OPTIONS_V2}
        return schema.model_validate(obj)


def test_v3_frozen_schema_and_prompt_require_report_voice_and_explicit_metric_label():
    memo, sources, proof = fixture()
    _, _, v2, _ = author.frozen_unit_requests(memo, sources, proof, PIN)
    _, _, v3, _ = author.frozen_unit_requests(memo, sources, proof, PIN, contract=author.CONTRACT_V3)
    assert all(payload['contract'] == author.CONTRACT_V3 for _, payload, _ in v3)
    schema = v3[0][2].model_json_schema()
    description = schema['properties']['standalone_text']['description']
    assert 'explicitly attributing' in description and 'economic metric label' in description
    assert 'not demonstrated results' in description
    assert 'Currency, units, potential' in author.INSTRUCTION_V3
    assert 'independently established result' in author.INSTRUCTION_V3
    assert v2[0][2].model_json_schema() != schema
    assert 'REPORTING DISCIPLINE' not in author.INSTRUCTION_V2


def test_v3_recorded_units_replay_and_v2_default_contract_remains_exact():
    memo, sources, proof = fixture()
    rows, model = [], Model()
    for _ in range(3):
        record = author.run_author(memo, sources, proof, PIN, rows, lambda: None, model,
            PreparationBudget(105, max_calls=6, max_requests=6), contract=author.CONTRACT_V3)
    assert record['state'] == 'accepted' and record['contract'] == author.CONTRACT_V3
    assert author.run_author(memo, sources, proof, PIN, rows, lambda: None, None,
        SimpleNamespace(calls=0, max_calls=0), contract=author.CONTRACT_V3) == record
    legacy_rows = []
    for _ in range(3):
        legacy = advance(memo, sources, proof, legacy_rows, V2Model())
    assert legacy['state'] == 'accepted' and legacy['contract'] == author.CONTRACT_V2
    assert author.run_author(memo, sources, proof, PIN, legacy_rows, lambda: None, None,
        SimpleNamespace(calls=0, max_calls=0), contract=author.CONTRACT_V2) == legacy
