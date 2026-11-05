"""Allowlisted two-transport reviewer capacity diagnostic; not expert acceptance.

The material schema/source/semantic contract stays unchanged. This profile only
adds an explicit bounded-thinking transport and its independently bound replay.
No product model default, source selection or human release gate changes.
"""
from __future__ import annotations

from copy import deepcopy
import json
from typing import get_args

from pydantic import Field, create_model


PROFILE = 'qwen3-8b-bounded-material-review-v1'
TASK = 'material_argument_compact_review_v2'
SEMANTIC_CONTRACT = 'source-bound-im-compact-review-v2'
MODEL_PIN = {'name': 'qwen3:8b',
    'digest': '500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41'}
OPTIONS = {'thinking': True, 'reasoning_budget': 256, 'max_tokens': 1156,
    'context_tokens': 8192, 'temperature': 0.6, 'bound_strings': True,
    'compact_prompt': True, 'require_full_context': True, 'factual_sampling': True,
    'bounded_thinking_contract': 'local-bounded-thinking-v1',
    'runtime_options': {'num_gpu': 28, 'num_batch': 128}}
SAMPLING = {'top_p': .95, 'top_k': 20, 'min_p': 0,
            'presence_penalty': 0, 'repeat_penalty': 1}
SUPPORT = ('supports', 'partial', 'does_not_support', 'unassessed')
VERDICTS = ('pass', 'revise', 'unassessed')
CATEGORIES = ('none', 'entailment', 'entity_or_metric', 'period_or_status',
              'missing_qualifier', 'reasoning_depth', 'countercase', 'scope',
              'repetition', 'unassessed')


def frozen_review_request(author_request, author_row):
    """Reuse every original unit, exact draft and complete B/Q vote inventory."""
    from delivery import material_argument as material
    from agents.research import document_generation as generation
    base = material.frozen_compact_argument_review_request(author_request, author_row, MODEL_PIN)
    overrides = {}
    for name, field in base[3].model_fields.items():
        if name.startswith('B') or name == 'section_coherence':
            vote = create_model(name + 'BoundedReviewShort80', __base__=field.annotation,
                reason=(str, Field(min_length=1, max_length=80)))
            overrides[name] = (vote, ...)
    schema = create_model('BoundedThinkingMaterialReviewV1', __base__=base[3], **overrides)
    payload = deepcopy(base[2])
    for key in ('request_binding_digest', 'schema_order_digest', 'generation_schema_order_digest'):
        payload.pop(key)
    payload.update(options=deepcopy(OPTIONS), review_capacity_profile=PROFILE,
        reviewer_relationship='separate_model_unqualified',
        capacity_status='unqualified_bounded_thinking_diagnostic')
    request = generation._request(TASK, base[1] +
        ' This is a bounded-thinking capacity diagnostic, not expert acceptance. '
        'Every reason is at most 80 characters. Preserve ALL original source units, '
        'the exact draft and every B/coherence/Q vote field.', payload, schema)
    validate_request(request[0], request[2], schema)
    if (payload['units'] != base[2]['units'] or
            payload['proposed_section'] != base[2]['proposed_section'] or
            payload['exact_rendered_section'] != base[2]['exact_rendered_section'] or
            payload['block_inventory'] != base[2]['block_inventory']):
        raise ValueError('bounded_review_changed_full_source_or_draft')
    return request


def validate_request(task, payload, schema):
    """An unknown profile/model/options or reduced vote schema fails closed."""
    if (task != TASK or payload.get('contract') != SEMANTIC_CONTRACT or
            payload.get('review_capacity_profile') != PROFILE or
            payload.get('model_pin') != MODEL_PIN or payload.get('options') != OPTIONS or
            payload.get('reviewer_relationship') != 'separate_model_unqualified' or
            payload.get('capacity_status') != 'unqualified_bounded_thinking_diagnostic'):
        raise ValueError('bounded_review_capacity_profile_not_allowlisted')
    blocks = payload.get('proposed_section', {}).get('blocks', [])
    inventory = payload.get('block_inventory', [])
    ids = [f'B{i}' for i in range(1, len(blocks) + 1)]
    if (not 4 <= len(blocks) <= 7 or inventory != [
            {'block_id': bid, 'index': i, 'role': block['role']}
            for i, (bid, block) in enumerate(zip(ids, blocks))]):
        raise ValueError('bounded_review_requires_complete_block_inventory')
    expected = set(ids) | {'overall_verdict', 'section_coherence', 'financial_status'}
    if (set(schema.model_fields) != expected or
            get_args(schema.model_fields['overall_verdict'].annotation) != VERDICTS or
            get_args(schema.model_fields['financial_status'].annotation) != ('not_established',)):
        raise ValueError('bounded_review_reduced_or_changed_vote_schema')
    for bid in ids + ['section_coherence']:
        vote = schema.model_fields[bid].annotation
        fields = {'verdict', 'category', 'reason'} | ({'selected_quote_support'} if bid in ids else set())
        if (set(vote.model_fields) != fields or
                get_args(vote.model_fields['verdict'].annotation) != VERDICTS or
                get_args(vote.model_fields['category'].annotation) != CATEGORIES or
                vote.model_json_schema()['properties']['reason'].get('maxLength') != 80):
            raise ValueError('bounded_review_changed_reason_or_vote_fields')
        if bid in ids:
            selected = blocks[ids.index(bid)]['evidence_handles']
            support = vote.model_fields['selected_quote_support'].annotation
            if (len(set(selected)) != len(selected) or set(support.model_fields) != set(selected) or
                    any(get_args(field.annotation) != SUPPORT for field in support.model_fields.values())):
                raise ValueError('bounded_review_reduced_or_foreign_Q_support_inventory')


def validate_receipts(instruction, payload, schema, routing, raw_response):
    from agents.inference.local_models import (
        bounded_thinking_input_binding, validate_bounded_thinking_receipts)
    if routing.get('sampling') != SAMPLING:
        raise ValueError('bounded_review_actual_sampling_changed')
    binding = bounded_thinking_input_binding(instruction, json.dumps(payload, ensure_ascii=False),
        schema, compact_prompt=True, bound_strings=True)
    # This validates both phase allocations and their full-context receipts.
    # The final prompt already contains the thought; do NOT charge its context
    # headroom the total reasoning+answer allocation for a second time.
    validate_bounded_thinking_receipts(routing, raw_response=raw_response,
                                       expected_input_binding=binding)
