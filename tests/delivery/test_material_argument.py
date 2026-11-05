"""Synthetic source/countercase/projection and exported pair regressions."""
from copy import deepcopy
from io import BytesIO
import json

import pytest
from pptx import Presentation
from pptx.util import Inches

from agents.inference.model_authorship import digest
from agents.research.document_evidence_manifest import build_document_manifest
from agents.research import document_generation as generation
from delivery import material_argument as argument
from delivery.rendering import render_argument_memo, render_evidence_document


PIN = {'name': 'qwen3.5:9b', 'digest': 'a' * 64}


def prepared(*, handles=False):
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(2))
    box.text = 'The source reports a limited pilot in 2024. Base scenario, vintage October 2024.'
    box.text_frame.add_paragraph().text = 'Retention was not measured in this source scope.'
    box.text_frame.add_paragraph().text = 'A different entity reported 120 during its pilot.'
    content = BytesIO(); deck.save(content)
    manifest = build_document_manifest(content.getvalue(), 'pptx', tenant_id='technical',
                                      deal_id='synthetic', document_id='source')
    request = argument.frozen_argument_request(manifest, [1], PIN,
                                              mandate='Historical synthetic argument diagnostic.')
    if not handles:
        # Historical V2 quote-copy replay remains covered; its actual failure
        # is retained rather than being retroactively accepted by V3 selectors.
        payload = deepcopy(request[2])
        for key in ('request_binding_digest', 'schema_order_digest', 'generation_schema_order_digest'):
            payload.pop(key)
        payload['contract'] = argument.CONTRACT_V2
        request = generation._request('material_argument_v2', argument.INSTRUCTION,
                                      payload, argument.ArgumentSection)
    unit = request[2]['units'][0]
    quote = {'unit_id': unit['id'], 'quote': unit['content']}
    answer = {'title': 'Pilot scope and the case for further diligence', 'blocks': [
        {'role': role, 'text': text, 'basis': basis, 'evidence': [quote],
         'source_vintage': '', 'scenario': ''}
        for role, text, basis in [
            ('evidence', 'The source reports a limited pilot in 2024.', 'reported'),
            ('implication', 'The limited scope may leave repeatability uncertain.', 'inference'),
            ('countercase', 'A limited pilot may deliberately narrow the test rather than imply weak demand.', 'inference'),
            ('next_diligence', 'What evidence would distinguish a deliberately narrow test from weak repeatability?', 'evidence_gap')]]}
    if handles:
        for block in answer['blocks']:
            block.pop('evidence')
            block['evidence_handles'] = ['Q1']
    return manifest, request, answer


def record(request, answer):
    task, instruction, payload, schema = request
    raw = json.dumps(answer)
    return {'id': 'response_1', 'task': task, 'instruction': instruction,
        'input': deepcopy(payload), 'schema': schema.model_json_schema(), 'answer': deepcopy(answer),
        'raw_response': raw, 'response_hash': digest(raw), 'model': payload['model_pin']['name'],
        'routing': {**payload['options'], 'model': payload['model_pin']['name'], 'prompt_tokens': 1100,
            'generated_tokens': 150, 'done_reason': 'stop',
            'sampling': {'presence_penalty': 0, 'repeat_penalty': 1},
            'format_object_receipts': [{'operation': 'chat', 'model': payload['model_pin']['name'],
                'format_order_digest': payload['generation_schema_order_digest']}]}}


def test_exact_source_argument_does_not_change_model_prose():
    _, request, answer = prepared()
    row = record(request, answer)
    assert argument.replay_argument(request, row) == answer
    section = argument.renderable_argument(request, row)
    assert all(b['text'] in section[1] for b in answer['blocks'])
    assert 'inference' in section[1] and 'historical' in section[2].lower()


@pytest.mark.parametrize('mutation,error', [
    (lambda a: a['blocks'][0]['evidence'][0].update(quote='invented quotation'), 'quote_not_in'),
    (lambda a: a['blocks'][0].update(text='The pilot had 999 customers.'), 'number_or_date'),
    (lambda a: a['blocks'][1].update(basis='reported'), 'remain_inference'),
    (lambda a: a['blocks'][3].update(basis='reported'), 'question_cannot'),
    (lambda a: a['blocks'][2].update(role='evidence'), 'missing_evidence'),
    (lambda a: a['blocks'][2].update(text=a['blocks'][1]['text']), 'repeated_block'),
    (lambda a: a['blocks'][0].update(basis='company_projection'), 'quoted_vintage'),
    (lambda a: a['blocks'][0].update(scenario='invented'), 'nonprojection'),
    (lambda a: a.update(title='The pilot had 999 customers'), 'title_number'),
])
def test_wrong_source_scope_and_argument_shortcuts_fail(mutation, error):
    _, request, answer = prepared(); mutation(answer)
    with pytest.raises(generation.GenerationError, match=error):
        argument.replay_argument(request, record(request, answer))


def test_projection_requires_both_verbatim_vintage_and_scenario():
    _, request, answer = prepared()
    answer['blocks'][0].update(basis='company_projection', source_vintage='October 2024', scenario='Base')
    row = record(request, answer)
    assert argument.replay_argument(request, row) == answer
    assert 'vintage: October 2024; scenario: Base' in argument.renderable_argument(request, row)[1]
    answer['blocks'][0]['source_vintage'] = 'November 2024'
    with pytest.raises(generation.GenerationError, match='quoted_vintage'):
        argument.replay_argument(request, record(request, answer))


def test_manifest_mutation_and_nonexistent_page_are_not_silently_retrieved():
    manifest, _, _ = prepared()
    with pytest.raises(generation.GenerationError, match='complete_original_pages'):
        argument.frozen_argument_request(manifest, [2], PIN, mandate='Synthetic')
    manifest['units'][0]['content'] += ' modified'
    with pytest.raises(generation.GenerationError, match='manifest_binding'):
        argument.frozen_argument_request(manifest, [1], PIN, mandate='Synthetic')


def test_compact_handles_retain_every_original_literal_and_exact_lineage():
    manifest, request, _ = prepared()
    bindings = argument.source_unit_bindings(manifest, [1])
    assert request[2]['source_unit_bindings_digest'] == generation.canonical_digest(bindings)
    assert [u['content'] for u in request[2]['units']] == [u['content'] for u in manifest['units']]
    assert [u['id'] for u in request[2]['units']] == [u['handle'] for u in bindings]
    assert [u['id'] for u in bindings] == [u['id'] for u in manifest['units']]
    assert all(u['source_locator'] and u['content_sha256'] and u['source_id'] for u in bindings)


def test_v3_projects_only_recorded_handles_without_retyping_or_rewriting():
    _, request, answer = prepared(handles=True)
    row = record(request, answer)
    projected = argument.replay_argument(request, row)
    assert row['answer'] == answer and 'evidence' not in answer['blocks'][0]
    assert [b['text'] for b in projected['blocks']] == [b['text'] for b in answer['blocks']]
    assert all(b['evidence'] == [{'unit_id': 'U1', 'quote': request[2]['units'][0]['content']}]
               for b in projected['blocks'])
    assert projected['blocks'][0]['evidence'][0]['quote'] in argument.source_unit_bindings(prepared()[0], [1])[0]['content']


def test_v3_wrong_handle_or_wrong_unit_numbers_are_not_repaired():
    _, request, answer = prepared(handles=True)
    answer['blocks'][0]['evidence_handles'] = ['Q999']
    with pytest.raises(ValueError):
        argument.replay_argument(request, record(request, answer))
    answer['blocks'][0]['evidence_handles'] = ['Q2']
    with pytest.raises(generation.GenerationError, match='number_or_date'):
        argument.replay_argument(request, record(request, answer))
    answer['blocks'][0]['evidence_handles'] = ['Q1', 'Q1']
    with pytest.raises(generation.GenerationError, match='duplicate_quote_handle'):
        argument.replay_argument(request, record(request, answer))


def test_v4_decoder_schema_forbids_nonprojection_metadata_and_wrong_role_basis():
    _, request, answer = prepared(handles=True)
    assert request[0] == 'material_argument_v4'
    assert request[3].model_validate(answer).model_dump(mode='json') == answer
    for field in ('source_vintage', 'scenario'):
        changed = deepcopy(answer); changed['blocks'][0][field] = 'unknown'
        with pytest.raises(ValueError):
            request[3].model_validate(changed)
    changed = deepcopy(answer); changed['blocks'][1]['basis'] = 'reported'
    with pytest.raises(ValueError):
        request[3].model_validate(changed)
    changed = deepcopy(answer); changed['blocks'][3]['basis'] = 'inference'
    with pytest.raises(ValueError):
        request[3].model_validate(changed)


def test_v4_projection_still_requires_exact_source_vintage_and_scenario():
    _, request, answer = prepared(handles=True)
    answer['blocks'][0].update(basis='company_projection', source_vintage='October 2024', scenario='Base')
    assert argument.replay_argument(request, record(request, answer))['blocks'][0]['basis'] == 'company_projection'
    answer['blocks'][0]['scenario'] = 'Invented'
    with pytest.raises(generation.GenerationError, match='quoted_vintage'):
        argument.replay_argument(request, record(request, answer))


def test_v3_prior_schema_and_nonprojection_failure_remain_replayable():
    _, request, answer = prepared(handles=True)
    payload = deepcopy(request[2])
    for key in ('request_binding_digest', 'schema_order_digest', 'generation_schema_order_digest'):
        payload.pop(key)
    payload['contract'] = argument.CONTRACT_V3
    old = generation._request('material_argument_v3', argument.INSTRUCTION,
        payload, argument.argument_handle_schema(payload['units']))
    assert argument.replay_argument(old, record(old, answer))['title'] == answer['title']
    answer['blocks'][0]['source_vintage'] = 'historical'
    with pytest.raises(generation.GenerationError, match='nonprojection'):
        argument.replay_argument(old, record(old, answer))


def compact_review_prepared():
    _, author_request, answer = prepared(handles=True)
    author_row = record(author_request, answer)
    request = argument.frozen_compact_argument_review_request(author_request, author_row, PIN)
    vote = {'verdict': 'pass', 'category': 'none', 'reason': 'Supported within the limited synthetic scope.'}
    review = {'overall_verdict': 'pass', 'financial_status': 'not_established',
              **{item['block_id']: {**deepcopy(vote), 'selected_quote_support': {
                  q: 'supports' for q in author_row['answer']['blocks'][item['index']]['evidence_handles']}}
                 for item in request[2]['block_inventory']},
              'section_coherence': deepcopy(vote)}
    return author_request, author_row, request, review


def test_compact_review_freezes_same_author_body_hash_and_full_original_sources():
    author_request, author_row, request, review = compact_review_prepared()
    assert request[2]['proposed_section'] == author_row['answer']
    assert request[2]['exact_rendered_section'] == list(argument.renderable_argument(author_request, author_row))
    assert request[2]['author_response_hash'] == author_row['response_hash']
    assert request[2]['source_unit_bindings_digest'] == author_request[2]['source_unit_bindings_digest']
    assert request[2]['units'] == author_request[2]['units']
    assert argument.replay_compact_argument_review(request, record(request, review)) == review
    author_row['raw_response'] += ' '
    with pytest.raises(ValueError, match='modified'):
        argument.frozen_compact_argument_review_request(author_request, author_row, PIN)


def test_compact_review_requires_every_block_and_cannot_override_a_critique():
    _, _, request, review = compact_review_prepared()
    missing = deepcopy(review); missing.pop('B2')
    with pytest.raises(ValueError):
        argument.replay_compact_argument_review(request, record(request, missing))
    review['B2'].update(verdict='revise', category='reasoning_depth',
                        reason='The implication repeats the observation without a supported mechanism.')
    with pytest.raises(generation.GenerationError, match='override_a_blocking_vote'):
        argument.replay_compact_argument_review(request, record(request, review))
    review['overall_verdict'] = 'revise'
    assert argument.replay_compact_argument_review(request, record(request, review))['overall_verdict'] == 'revise'


def test_compact_review_unassessed_and_category_mismatch_do_not_pass():
    _, _, request, review = compact_review_prepared()
    review['B1'].update(verdict='unassessed', category='unassessed', reason='Source meaning remains unresolved.')
    review['overall_verdict'] = 'unassessed'
    assert argument.replay_compact_argument_review(request, record(request, review))['overall_verdict'] == 'unassessed'
    review['B1']['category'] = 'none'
    with pytest.raises(generation.GenerationError, match='category_inconsistent'):
        argument.replay_compact_argument_review(request, record(request, review))


def test_compact_review_output_limit_and_source_input_tamper_are_still_failures():
    _, _, request, review = compact_review_prepared()
    row = record(request, review); row['routing']['done_reason'] = 'length'
    with pytest.raises(generation.GenerationError, match='incomplete_or_unbounded'):
        argument.replay_compact_argument_review(request, row)
    row = record(request, review); row['input']['units'][0]['content'] += ' substituted'
    with pytest.raises(generation.GenerationError, match='differs_from_frozen_request'):
        argument.replay_compact_argument_review(request, row)


def correction_prepared(*, coherence=True):
    original, original_row, review_request, review = compact_review_prepared()
    review['B1'].update(verdict='revise', category='entity_or_metric', reason='Recheck the pilot scope qualifier.')
    review['B1']['selected_quote_support']['Q1'] = 'partial'
    if coherence:
        review['section_coherence'].update(verdict='revise', category='reasoning_depth',
                                          reason='The section needs a clearer source-backed mechanism.')
    review['overall_verdict'] = 'revise'
    review_row = record(review_request, review)
    request = argument.frozen_argument_correction_request(original, original_row,
                                                          review_request, review_row, PIN)
    answer = deepcopy(original_row['answer'])
    answer.update(patch_scope=['B1'], scope_reason='Address the source scope critique without changing other blocks.')
    answer['blocks'][0]['text'] = 'The 2024 source describes a limited pilot.'
    return original, original_row, review_request, review_row, request, answer


def test_correction_is_full_recorded_model_prose_and_preserves_other_blocks():
    original, original_row, _, review_row, request, answer = correction_prepared()
    before = deepcopy(original_row)
    corrected_row = record(request, answer)
    result = argument.replay_argument(request, corrected_row)
    assert result['blocks'][0]['text'] == answer['blocks'][0]['text']
    assert corrected_row['answer']['blocks'][1:] == original_row['answer']['blocks'][1:]
    assert original_row == before
    assert request[2]['correction_context']['blocking_review_response_hash'] == review_row['response_hash']
    fresh = argument.frozen_compact_argument_review_request(request, corrected_row, PIN)
    assert 'correction_context' not in fresh[2] and 'blocking_review' not in fresh[2]
    assert fresh[2]['proposed_section'] == {key: answer[key] for key in ('title', 'blocks')}
    assert fresh[2]['units'] == original[2]['units']
    assert fresh[2]['author_response_hash'] != original_row['response_hash']


def test_correction_cannot_silently_rewrite_untargeted_or_skip_required_block():
    _, _, _, _, request, answer = correction_prepared()
    answer['blocks'][1]['text'] += ' A new unsupported implication.'
    with pytest.raises(generation.GenerationError, match='scope_differs'):
        argument.replay_argument(request, record(request, answer))
    _, original_row, _, _, request, answer = correction_prepared()
    answer['blocks'][0] = deepcopy(original_row['answer']['blocks'][0])
    answer['blocks'][1]['text'] += ' A bounded conditional interpretation.'
    answer['patch_scope'] = ['B2']
    with pytest.raises(generation.GenerationError, match='omitted_critique'):
        argument.replay_argument(request, record(request, answer))


def test_correction_expanded_scope_requires_actual_section_level_critique():
    _, _, _, _, request, answer = correction_prepared(coherence=False)
    answer['blocks'][1]['text'] += ' The narrow test may limit generalization.'
    answer['patch_scope'].append('B2')
    with pytest.raises(generation.GenerationError, match='changed_untargeted'):
        argument.replay_argument(request, record(request, answer))


def test_correction_cannot_use_another_review_or_start_recursive_repair_loops():
    original, original_row, review_request, review_row, request, answer = correction_prepared()
    substituted = deepcopy(review_request); substituted[2]['author_response_hash'] = 'f' * 64
    with pytest.raises(generation.GenerationError, match='not_bound_to_original_author'):
        argument.frozen_argument_correction_request(original, original_row, substituted, review_row, PIN)
    correction_row = record(request, answer)
    fresh = argument.frozen_compact_argument_review_request(request, correction_row, PIN)
    with pytest.raises(generation.GenerationError, match='not_a_retry_loop'):
        argument.frozen_argument_correction_request(request, correction_row, fresh, review_row, PIN)


@pytest.mark.parametrize('vintage,scenario', [('2', 'Base'), ('2024', 'Base'),
                                            ('October 2024', 'e'), ('October 2024', 'ase')])
def test_projection_rejects_substring_vintage_and_scenario(vintage, scenario):
    _, request, answer = prepared()
    answer['blocks'][0].update(basis='company_projection', source_vintage=vintage, scenario=scenario)
    with pytest.raises(generation.GenerationError, match='quoted_vintage'):
        argument.replay_argument(request, record(request, answer))


def test_projection_cannot_union_a_figure_from_another_quote_with_its_vintage():
    _, request, answer = prepared()
    block = answer['blocks'][0]
    block.update(text='The projection is 120.', basis='company_projection',
                 source_vintage='October 2024', scenario='Base')
    block['evidence'].append({'unit_id': 'U3', 'quote': request[2]['units'][2]['content']})
    with pytest.raises(generation.GenerationError, match='quoted_vintage'):
        argument.replay_argument(request, record(request, answer))
    assert not argument._projection_same_quote({'source_vintage': '2024-02-30', 'scenario': 'Base',
        'text': 'Projected 120.', 'evidence': [{'quote': 'Base scenario, vintage 2024-02-30: 120.'}]})


def test_source_matrix_requires_every_selected_Q_and_identifies_entity_defect():
    _, _, request, review = compact_review_prepared()
    assert request[2]['reviewer_relationship'] == 'same_model_nonindependent'
    missing = deepcopy(review); missing['B1']['selected_quote_support'].pop('Q1')
    with pytest.raises(ValueError):
        argument.replay_compact_argument_review(request, record(request, missing))
    foreign = deepcopy(review); foreign['B1']['selected_quote_support']['Q999'] = 'supports'
    with pytest.raises(ValueError):
        argument.replay_compact_argument_review(request, record(request, foreign))
    review['B1']['selected_quote_support']['Q1'] = 'partial'
    with pytest.raises(generation.GenerationError, match='every_chosen_quote_support'):
        argument.replay_compact_argument_review(request, record(request, review))
    review['B1'].update(verdict='revise', category='entity_or_metric')
    review['overall_verdict'] = 'revise'
    assert argument.replay_compact_argument_review(request, record(request, review))['B1']['category'] == 'entity_or_metric'
    review['B1']['selected_quote_support']['Q1'] = 'supports'
    with pytest.raises(generation.GenerationError, match='identified_quote'):
        argument.replay_compact_argument_review(request, record(request, review))


def test_legacy_v1_votes_and_v2_required_request_digests_remain_replayable():
    _, old_author, answer = prepared()
    assert {'request_binding_digest', 'schema_order_digest', 'generation_schema_order_digest'} <= set(old_author[2])
    argument.frozen_argument_review_request(old_author, record(old_author, answer), PIN)
    _, original, answer = prepared(handles=True)
    row = record(original, answer)
    old_review = argument.frozen_compact_argument_review_request(original, row, PIN,
        review_contract=argument.COMPACT_REVIEW_CONTRACT_V1)
    vote = {'verdict': 'pass', 'category': 'none', 'reason': 'Synthetic legacy review only.'}
    review = {'overall_verdict': 'pass', 'financial_status': 'not_established',
              **{item['block_id']: deepcopy(vote) for item in old_review[2]['block_inventory']},
              'section_coherence': deepcopy(vote)}
    assert argument.replay_compact_argument_review(old_review, record(old_review, review)) == review
    with pytest.raises(generation.GenerationError, match='source_matrix_review_v2'):
        argument.frozen_argument_patch_request(original, row, old_review, record(old_review, review), PIN)


def patch_prepared():
    original, original_row, review_request, review_row, _, _ = correction_prepared()
    request = argument.frozen_argument_patch_request(original, original_row, review_request, review_row, PIN)
    answer = {'patches': {bid: None for bid in request[2]['patch_context']['permitted_patch_ids']},
              'scope_reason': 'Correct the pilot scope without inventing new facts.'}
    answer['patches']['B1'] = deepcopy(original_row['answer']['blocks'][0])
    answer['patches']['B1']['text'] = 'The 2024 source describes a limited pilot.'
    return original, original_row, request, answer


def test_finite_patch_keys_project_only_recorded_nonnull_blocks_and_preserve_base():
    original, original_row, request, answer = patch_prepared()
    before = deepcopy(original_row)
    row = record(request, answer)
    result = argument.replay_argument(request, row)
    projected = argument._project_argument_patch(request, answer)
    assert result['recorded_patch_scope'] == ['B1'] and 'patch_scope' not in row['answer']
    assert projected['title'] == original_row['answer']['title']
    assert projected['blocks'][1:] == original_row['answer']['blocks'][1:]
    assert original_row == before
    assert result['blocks'][0]['text'] == answer['patches']['B1']['text']
    fresh = argument.frozen_compact_argument_review_request(request, row, PIN)
    assert 'patch_context' not in fresh[2]
    assert fresh[2]['proposed_section'] == {key: projected[key] for key in ('title', 'blocks')}
    assert fresh[2]['units'] == original[2]['units']
    assert fresh[2]['author_response_hash'] == row['response_hash']


def test_finite_patch_schema_cannot_change_title_role_or_unknown_block_or_omit_critique():
    _, _, request, answer = patch_prepared()
    for change in ('title', 'foreign', 'role', 'null_required'):
        changed = deepcopy(answer)
        if change == 'title':
            changed['title'] = 'Unrecorded title rewrite'
        elif change == 'foreign':
            changed['patches']['B999'] = deepcopy(changed['patches']['B1'])
        elif change == 'role':
            changed['patches']['B1'].update(role='countercase', basis='inference')
        else:
            changed['patches']['B1'] = None
        with pytest.raises(ValueError):
            argument.replay_argument(request, record(request, changed))


def test_finite_patch_does_not_repair_bad_numbers_or_allow_noop_replacement():
    _, original_row, request, answer = patch_prepared()
    answer['patches']['B1']['text'] = 'The source pilot had 999 customers.'
    with pytest.raises(generation.GenerationError, match='number_or_date'):
        argument.replay_argument(request, record(request, answer))
    answer['patches']['B1'] = deepcopy(original_row['answer']['blocks'][0])
    with pytest.raises(generation.GenerationError, match='did_not_change'):
        argument.replay_argument(request, record(request, answer))


def test_raw_and_actual_frozen_options_tampering_fail_before_projection():
    _, request, answer = prepared()
    row = record(request, answer); row['raw_response'] += ' '
    with pytest.raises(ValueError, match='modified'):
        argument.replay_argument(request, row)
    row = record(request, answer); row['routing']['context_tokens'] = 8192
    with pytest.raises(generation.GenerationError, match='actual_model_options'):
        argument.replay_argument(request, row)


def test_independent_review_needs_real_block_phrase_and_consistent_verdict():
    _, request, answer = prepared(); row = record(request, answer)
    review_request = argument.frozen_argument_review_request(request, row, PIN)
    review = {'verdict': 'revise', 'financial_status': 'not_established', 'issues': [
        {'block_index': 1, 'kind': 'shallow_reasoning', 'exact_phrase': 'limited scope',
         'explanation': 'The rationale is too broad to support a complete memo.'}]}
    assert argument.replay_argument_review(review_request, record(review_request, review)) == review
    review['issues'][0]['exact_phrase'] = 'nonexistent phrase'
    with pytest.raises(generation.GenerationError, match='actual_block'):
        argument.replay_argument_review(review_request, record(review_request, review))
    review.update(issues=[], verdict='revise')
    with pytest.raises(generation.GenerationError, match='inconsistent'):
        argument.replay_argument_review(review_request, record(review_request, review))


def test_longer_argument_pair_preserves_every_paragraph_and_legacy_limit():
    from docx import Document
    from pypdf import PdfReader
    paragraphs = [('Synthetic technical paragraph ' + str(i) + ': ' +
                   'This sentence exercises pagination without any investment claim. ' * 10)
                  for i in range(6)]
    section = ('Synthetic technical section', '\n\n'.join(paragraphs), 'Source: synthetic only')
    docx = Document(BytesIO(render_argument_memo('Technical diagnostic', [section], format='docx')))
    assert all(p in [v.text for v in docx.paragraphs] for p in paragraphs)
    pdf = PdfReader(BytesIO(render_argument_memo('Technical diagnostic', [section], format='pdf')))
    text = '\n'.join(p.extract_text() for p in pdf.pages)
    assert len(pdf.pages) >= 2
    assert all('Synthetic technical paragraph ' + str(i) in text for i in range(6))
    with pytest.raises(ValueError, match='split'):
        render_evidence_document('Legacy limit', [section], kind='investment_memorandum', format='pdf')
    with pytest.raises(ValueError, match='paragraph'):
        render_argument_memo('No clipping', [('Section', 'x' * 1600, '')], format='pdf')
