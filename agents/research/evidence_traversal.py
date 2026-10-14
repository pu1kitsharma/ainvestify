'''Deterministic freeze/verify helper for a bounded two-stage local-model workflow.'''
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Tuple

MAX_SOURCES, BATCH_SIZE, MAX_CALLS = 25, 5, 6


class TraversalError(ValueError):
    def __init__(self, code, detail=''):
        super().__init__(code + (': ' + detail if detail else ''))
        self.code, self.detail = code, detail


def _fail(code, detail=''):
    raise TraversalError(code, detail)


def _canon(obj):
    try:
        text = json.dumps(obj, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False)
        text.encode('utf-8')
    except (TypeError, ValueError):
        raise TraversalError('not_canonical') from None
    return text


def _digest(obj):
    return 'sha256:' + hashlib.sha256(_canon(obj).encode('utf-8')).hexdigest()


def _text(v):
    return isinstance(v, str) and bool(v.strip())


@dataclass(frozen=True)
class SourceRef:
    id: str
    version_digest: str
    content_digest: str


@dataclass(frozen=True)
class Batch:
    index: int
    key: str
    sources: Tuple[SourceRef, ...]

    @property
    def source_ids(self):
        return tuple(s.id for s in self.sources)


@dataclass(frozen=True)
class Plan:
    inventory_digest: str
    input_revision: str
    model_name: str
    model_digest: str
    options_json: str
    batches: Tuple[Batch, ...]
    selection_binding: str
    plan_digest: str
    call_budget: int


@dataclass(frozen=True)
class Verification:
    plan_digest: str
    admitted_ids: Tuple[str, ...]
    selected_ids: Tuple[str, ...]


@dataclass(frozen=True)
class AdjudicatedPlan:
    """Fresh three-stage wrapper; original classification batch keys stay exact."""
    classification_plan: Plan
    adjudication_options_json: str
    selection_options_json: str
    adjudication_binding: str
    selection_binding: str
    plan_digest: str
    call_budget: int


@dataclass(frozen=True)
class RoleAdjudicatedPlan:
    """Explicit stage roles without changing historical single-model plans."""
    classification_plan: Plan
    adjudicator_model_name: str
    adjudicator_model_digest: str
    selector_model_name: str
    selector_model_digest: str
    adjudication_options_json: str
    selection_options_json: str
    adjudication_binding: str
    selection_binding: str
    plan_digest: str
    call_budget: int


@dataclass(frozen=True)
class ShardedAdjudicatedPlan:
    classification_plan: Plan
    adjudicator_model_name: str
    adjudicator_model_digest: str
    selector_model_name: str
    selector_model_digest: str
    adjudication_options_json: str
    selection_options_json: str
    shards: Tuple[Tuple[str, ...], ...]
    adjudication_bindings: Tuple[str, ...]
    selection_binding: str
    plan_digest: str
    call_budget: int


@dataclass(frozen=True)
class BlindSourceGroup:
    id: str
    source_ids: Tuple[str, ...]
    passage: str


@dataclass(frozen=True)
class BlindShardedPlan:
    source_plan: ShardedAdjudicatedPlan
    groups: Tuple[BlindSourceGroup, ...]
    adjudication_bindings: Tuple[str, ...]
    selection_binding: str
    plan_digest: str

    @property
    def classification_plan(self):
        return self.source_plan.classification_plan

    @property
    def shards(self):
        return self.source_plan.shards

    @property
    def call_budget(self):
        return self.source_plan.call_budget


@dataclass(frozen=True)
class DirectBlindPlan:
    inventory_plan: Plan
    selector_model_name: str
    selector_model_digest: str
    selection_options_json: str
    groups: Tuple[BlindSourceGroup, ...]
    shards: Tuple[Tuple[str, ...], ...]
    assessment_bindings: Tuple[str, ...]
    selection_binding: str
    plan_digest: str
    call_budget: int

    @property
    def adjudication_bindings(self):
        return self.assessment_bindings


def _build(refs, revision, name, model_digest, options_json):
    if not refs or len(refs) > MAX_SOURCES:
        _fail('bad_source_count')
    ids = [r.id for r in refs]
    if len(set(ids)) != len(ids):
        _fail('duplicate_id')
    rows = [[r.id, r.version_digest, r.content_digest] for r in refs]
    inventory = _digest(rows)
    ctx = {'revision': revision, 'model': [name, model_digest], 'options': options_json}
    batches = []
    for start in range(0, len(refs), BATCH_SIZE):
        idx = start // BATCH_SIZE
        key = _digest({'kind': 'classify', 'index': idx,
                       'sources': rows[start:start + BATCH_SIZE], 'ctx': ctx})
        batches.append(Batch(idx, key, tuple(refs[start:start + BATCH_SIZE])))
    binding = _digest({'kind': 'select', 'inventory': inventory,
                       'batches': [b.key for b in batches], 'ctx': ctx})
    return Plan(inventory, revision, name, model_digest, options_json, tuple(batches),
                binding, _digest({'inventory': inventory, 'binding': binding, 'ctx': ctx}),
                len(batches) + 1)


def freeze_traversal(sources, input_revision, model_pin, options):
    if not isinstance(sources, (list, tuple)):
        _fail('bad_sources')
    if not sources:
        _fail('no_sources')
    if len(sources) > MAX_SOURCES:
        _fail('too_many_sources')
    refs = []
    for s in sources:
        if not isinstance(s, Mapping) or set(s) != {'id', 'version', 'passage'}:
            _fail('malformed_source')
        if not all(_text(s[k]) for k in s):
            _fail('malformed_source')
        try:
            refs.append(SourceRef(s['id'], _digest({'id': s['id'], 'version': s['version']}),
                                  _digest(s['passage'])))
        except TraversalError:
            _fail('malformed_source')
    if not _text(input_revision):
        _fail('bad_revision')
    if (not isinstance(model_pin, Mapping) or set(model_pin) != {'name', 'digest'}
            or not _text(model_pin['name']) or not _text(model_pin['digest'])):
        _fail('bad_model_pin')
    if not isinstance(options, Mapping):
        _fail('bad_options')
    try:
        options_json = _canon(dict(options))
    except TraversalError:
        _fail('bad_options')
    return _build(tuple(refs), input_revision, model_pin['name'], model_pin['digest'], options_json)


def _check_batch(batch, rec):
    if not isinstance(rec, Mapping) or rec.get('batch_key') != batch.key:
        _fail('batch_key_mismatch', str(batch.index))
    results = rec.get('results')
    if not isinstance(results, (list, tuple)):
        _fail('malformed_result', str(batch.index))
    seen = []
    for r in results:
        if not isinstance(r, Mapping) or not isinstance(r.get('source_id'), str) \
                or 'classification' not in r:
            _fail('malformed_result', str(batch.index))
        _canon(r['classification'])
        seen.append(r['source_id'])
    if len(set(seen)) != len(seen):
        _fail('duplicate_result_id', str(batch.index))
    expected = set(batch.source_ids)
    if expected - set(seen):
        _fail('missing_result_id', str(batch.index))
    if set(seen) - expected:
        _fail('extra_result_id', str(batch.index))


def verify_traversal(plan, recorded_classifications, recorded_selection):
    if not isinstance(plan, Plan):
        _fail('plan_invalid')
    try:
        refs = tuple(r for b in plan.batches for r in b.sources)
        rebuilt = _build(refs, plan.input_revision, plan.model_name,
                         plan.model_digest, plan.options_json)
    except (TypeError, AttributeError, ValueError):
        _fail('plan_mismatch')
    if rebuilt != plan:
        _fail('plan_mismatch')
    if not isinstance(recorded_classifications, (list, tuple)):
        _fail('malformed_batches')
    if len(recorded_classifications) < len(plan.batches):
        _fail('incomplete_batches')
    if len(recorded_classifications) > len(plan.batches):
        _fail('extra_batches')
    for batch, rec in zip(plan.batches, recorded_classifications):
        _check_batch(batch, rec)
    admitted = tuple(i for b in plan.batches for i in b.source_ids)
    sel = recorded_selection
    if not isinstance(sel, Mapping):
        _fail('selection_missing')
    if sel.get('inventory_digest') != plan.inventory_digest:
        _fail('selection_inventory_mismatch')
    if sel.get('binding') != plan.selection_binding:
        _fail('selection_binding_mismatch')
    chosen = sel.get('selected_ids')
    if not isinstance(chosen, (list, tuple)) or not all(isinstance(i, str) for i in chosen):
        _fail('selection_malformed')
    if len(set(chosen)) != len(chosen):
        _fail('duplicate_selected_id')
    if set(chosen) - set(admitted):
        _fail('unadmitted_selected_id')
    return Verification(plan.plan_digest, admitted, tuple(chosen))


def _adjudicated_plan(base, adjudication_options_json, selection_options_json):
    adjudication = _digest({'stage': 'adjudicate', 'classification_plan': base.plan_digest,
                            'options': adjudication_options_json})
    selection = _digest({'stage': 'select_after_adjudication', 'classification_plan': base.plan_digest,
                         'adjudication_binding': adjudication, 'options': selection_options_json})
    return AdjudicatedPlan(base, adjudication_options_json, selection_options_json,
        adjudication, selection, _digest({'classification_plan': base.plan_digest,
            'adjudication': adjudication, 'selection': selection}), len(base.batches) + 2)


def freeze_adjudicated_traversal(sources, input_revision, model_pin, classification_options,
                                adjudication_options, selection_options):
    if not isinstance(adjudication_options, Mapping) or not isinstance(selection_options, Mapping):
        _fail('bad_options')
    base = freeze_traversal(sources, input_revision, model_pin, classification_options)
    return _adjudicated_plan(base, _canon(dict(adjudication_options)), _canon(dict(selection_options)))


def verify_adjudicated_traversal(plan, recorded_classifications, recorded_adjudication,
                                recorded_selection):
    if not isinstance(plan, AdjudicatedPlan):
        _fail('plan_invalid')
    base = plan.classification_plan
    try:
        refs = tuple(ref for batch in base.batches for ref in batch.sources)
        rebuilt_base = _build(refs, base.input_revision, base.model_name, base.model_digest, base.options_json)
        rebuilt = _adjudicated_plan(rebuilt_base, plan.adjudication_options_json, plan.selection_options_json)
    except (TypeError, AttributeError, ValueError):
        _fail('plan_mismatch')
    if rebuilt != plan:
        _fail('plan_mismatch')
    if (not isinstance(recorded_adjudication, Mapping) or
            recorded_adjudication.get('inventory_digest') != base.inventory_digest or
            recorded_adjudication.get('binding') != plan.adjudication_binding or
            not _text(recorded_adjudication.get('response_hash'))):
        _fail('adjudication_binding_mismatch')
    if (not isinstance(recorded_selection, Mapping) or
            recorded_selection.get('inventory_digest') != base.inventory_digest or
            recorded_selection.get('binding') != plan.selection_binding or
            recorded_selection.get('adjudication_response_hash') != recorded_adjudication['response_hash']):
        _fail('adjudicated_selection_binding_mismatch')
    checked = verify_traversal(base, recorded_classifications, {
        'inventory_digest': base.inventory_digest, 'binding': base.selection_binding,
        'selected_ids': recorded_selection.get('selected_ids')})
    return Verification(plan.plan_digest, checked.admitted_ids, checked.selected_ids)


def _role_adjudicated_plan(base, adjudicator_pin, selector_pin, adjudication_options_json,
                           selection_options_json):
    roles = {'classification': [base.model_name, base.model_digest],
             'adjudication': [adjudicator_pin['name'], adjudicator_pin['digest']],
             'selection': [selector_pin['name'], selector_pin['digest']]}
    adjudication = _digest({'stage': 'adjudicate', 'classification_plan': base.plan_digest,
                           'roles': roles, 'options': adjudication_options_json})
    selection = _digest({'stage': 'select_after_adjudication', 'classification_plan': base.plan_digest,
                         'roles': roles, 'adjudication_binding': adjudication,
                         'options': selection_options_json})
    return RoleAdjudicatedPlan(base, *roles['adjudication'], *roles['selection'],
        adjudication_options_json, selection_options_json, adjudication, selection,
        _digest({'classification_plan': base.plan_digest, 'roles': roles,
                 'adjudication': adjudication, 'selection': selection}), len(base.batches) + 2)


def freeze_role_adjudicated_traversal(sources, input_revision, classifier_pin, adjudicator_pin,
                                     selector_pin, classification_options, adjudication_options,
                                     selection_options):
    for pin in (adjudicator_pin, selector_pin):
        if (not isinstance(pin, Mapping) or set(pin) != {'name', 'digest'} or
                not _text(pin['name']) or not _text(pin['digest'])):
            _fail('bad_model_pin')
    if not isinstance(adjudication_options, Mapping) or not isinstance(selection_options, Mapping):
        _fail('bad_options')
    base = freeze_traversal(sources, input_revision, classifier_pin, classification_options)
    return _role_adjudicated_plan(base, adjudicator_pin, selector_pin,
        _canon(dict(adjudication_options)), _canon(dict(selection_options)))


def verify_role_adjudicated_traversal(plan, recorded_classifications, recorded_adjudication,
                                     recorded_selection):
    if not isinstance(plan, RoleAdjudicatedPlan):
        _fail('plan_invalid')
    base = plan.classification_plan
    try:
        refs = tuple(ref for batch in base.batches for ref in batch.sources)
        rebuilt_base = _build(refs, base.input_revision, base.model_name, base.model_digest, base.options_json)
        rebuilt = _role_adjudicated_plan(rebuilt_base,
            {'name': plan.adjudicator_model_name, 'digest': plan.adjudicator_model_digest},
            {'name': plan.selector_model_name, 'digest': plan.selector_model_digest},
            plan.adjudication_options_json, plan.selection_options_json)
    except (TypeError, AttributeError, ValueError):
        _fail('plan_mismatch')
    if rebuilt != plan:
        _fail('plan_mismatch')
    if (not isinstance(recorded_adjudication, Mapping) or
            recorded_adjudication.get('inventory_digest') != base.inventory_digest or
            recorded_adjudication.get('binding') != plan.adjudication_binding or
            not _text(recorded_adjudication.get('response_hash'))):
        _fail('adjudication_binding_mismatch')
    if (not isinstance(recorded_selection, Mapping) or
            recorded_selection.get('inventory_digest') != base.inventory_digest or
            recorded_selection.get('binding') != plan.selection_binding or
            recorded_selection.get('adjudication_response_hash') != recorded_adjudication['response_hash']):
        _fail('adjudicated_selection_binding_mismatch')
    checked = verify_traversal(base, recorded_classifications, {
        'inventory_digest': base.inventory_digest, 'binding': base.selection_binding,
        'selected_ids': recorded_selection.get('selected_ids')})
    return Verification(plan.plan_digest, checked.admitted_ids, checked.selected_ids)


def freeze_adjudication_shards(sources):
    """Five bounded bins; exact duplicates stay together, without semantic labels."""
    if not isinstance(sources, (list, tuple)) or not 1 <= len(sources) <= MAX_SOURCES:
        _fail('bad_source_count')
    groups, order = {}, {}
    for index, source in enumerate(sources):
        if (not isinstance(source, Mapping) or not _text(source.get('id')) or
                not _text(source.get('passage')) or source['id'] in order):
            _fail('malformed_source')
        order[source['id']] = index
        groups.setdefault(source['passage'], []).append(source['id'])
    if any(len(ids) > BATCH_SIZE for ids in groups.values()):
        _fail('duplicate_group_exceeds_shard_bound')
    pending = sorted(groups.values(), key=lambda ids: (-len(ids), order[ids[0]]))
    bins = [[] for _ in range(5)]
    failed = set()

    def assign(index):
        if index == len(pending):
            return True
        capacities = tuple(sorted(len(shard) for shard in bins))
        state = (index, capacities)
        if state in failed:
            return False
        group, tried = pending[index], set()
        for shard in bins:
            size = len(shard)
            if size in tried or size + len(group) > BATCH_SIZE:
                continue
            tried.add(size)
            shard.extend(group)
            if assign(index + 1):
                return True
            del shard[-len(group):]
        failed.add(state)
        return False

    if not assign(0):
        _fail('duplicate_groups_cannot_fit_five_shards')
    return tuple(tuple(sorted(shard, key=order.__getitem__)) for shard in bins)


def _sharded_adjudicated_plan(base, adjudicator_pin, selector_pin, adjudication_options_json,
                              selection_options_json, shards):
    admitted = tuple(sid for batch in base.batches for sid in batch.source_ids)
    flattened = tuple(sid for shard in shards for sid in shard)
    if (len(shards) != 5 or any(len(shard) > BATCH_SIZE for shard in shards) or
            len(flattened) != len(set(flattened)) or set(flattened) != set(admitted)):
        _fail('invalid_shard_inventory')
    roles = {'classification': [base.model_name, base.model_digest],
             'adjudication': [adjudicator_pin['name'], adjudicator_pin['digest']],
             'selection': [selector_pin['name'], selector_pin['digest']]}
    bindings = tuple(_digest({'stage': 'adjudicate_shard', 'index': index,
        'classification_plan': base.plan_digest, 'source_ids': ids, 'roles': roles,
        'options': adjudication_options_json}) for index, ids in enumerate(shards, 1))
    selection = _digest({'stage': 'select_after_shards', 'classification_plan': base.plan_digest,
        'shards': shards, 'adjudication_bindings': bindings, 'roles': roles,
        'options': selection_options_json})
    return ShardedAdjudicatedPlan(base, *roles['adjudication'], *roles['selection'],
        adjudication_options_json, selection_options_json, shards, bindings, selection,
        _digest({'classification_plan': base.plan_digest, 'roles': roles, 'shards': shards,
                 'adjudication': bindings, 'selection': selection}), len(base.batches) + 6)


def freeze_sharded_adjudicated_traversal(sources, input_revision, classifier_pin, adjudicator_pin,
                                        selector_pin, classification_options, adjudication_options,
                                        selection_options):
    for pin in (adjudicator_pin, selector_pin):
        if (not isinstance(pin, Mapping) or set(pin) != {'name', 'digest'} or
                not _text(pin['name']) or not _text(pin['digest'])):
            _fail('bad_model_pin')
    if not isinstance(adjudication_options, Mapping) or not isinstance(selection_options, Mapping):
        _fail('bad_options')
    base = freeze_traversal(sources, input_revision, classifier_pin, classification_options)
    return _sharded_adjudicated_plan(base, adjudicator_pin, selector_pin,
        _canon(dict(adjudication_options)), _canon(dict(selection_options)),
        freeze_adjudication_shards(sources))


def verify_sharded_adjudicated_traversal(plan, recorded_classifications, recorded_adjudications,
                                        recorded_selection):
    if not isinstance(plan, ShardedAdjudicatedPlan):
        _fail('plan_invalid')
    base = plan.classification_plan
    try:
        refs = tuple(ref for batch in base.batches for ref in batch.sources)
        rebuilt_base = _build(refs, base.input_revision, base.model_name, base.model_digest, base.options_json)
        rebuilt = _sharded_adjudicated_plan(rebuilt_base,
            {'name': plan.adjudicator_model_name, 'digest': plan.adjudicator_model_digest},
            {'name': plan.selector_model_name, 'digest': plan.selector_model_digest},
            plan.adjudication_options_json, plan.selection_options_json, plan.shards)
    except (TypeError, AttributeError, ValueError):
        _fail('plan_mismatch')
    if rebuilt != plan:
        _fail('plan_mismatch')
    # Content digests bind exact duplicate passages to the same shard.
    positions = {sid: index for index, shard in enumerate(plan.shards) for sid in shard}
    duplicate_positions = {}
    for ref in refs:
        duplicate_positions.setdefault(ref.content_digest, set()).add(positions[ref.id])
    if any(len(indices) > 1 for indices in duplicate_positions.values()):
        _fail('duplicate_group_split_between_shards')
    expected = [(index, binding) for index, (ids, binding) in
                enumerate(zip(plan.shards, plan.adjudication_bindings), 1) if ids]
    if not isinstance(recorded_adjudications, (list, tuple)) or len(recorded_adjudications) != len(expected):
        _fail('incomplete_adjudication_shards')
    for record, (index, binding) in zip(recorded_adjudications, expected):
        if (not isinstance(record, Mapping) or record.get('shard_index') != index or
                record.get('inventory_digest') != base.inventory_digest or record.get('binding') != binding or
                not _text(record.get('response_hash'))):
            _fail('adjudication_shard_binding_mismatch')
    selected = recorded_selection
    if (not isinstance(selected, Mapping) or selected.get('inventory_digest') != base.inventory_digest or
            selected.get('binding') != plan.selection_binding or
            selected.get('adjudication_responses_digest') != _digest(recorded_adjudications)):
        _fail('sharded_selection_binding_mismatch')
    checked = verify_traversal(base, recorded_classifications, {
        'inventory_digest': base.inventory_digest, 'binding': base.selection_binding,
        'selected_ids': selected.get('selected_ids')})
    return Verification(plan.plan_digest, checked.admitted_ids, checked.selected_ids)


def sharded_adjudication_digest(recorded_adjudications):
    return _digest(recorded_adjudications)


def freeze_blind_source_groups(sources):
    # Reuse generic inventory validation; exact passage bytes are the only grouping rule.
    freeze_adjudication_shards(sources)
    passages = {}
    for source in sources:
        passages.setdefault(source['passage'], []).append(source['id'])
    return tuple(BlindSourceGroup(f'G{index}', tuple(ids), passage)
                 for index, (passage, ids) in enumerate(passages.items(), 1))


def _blind_sharded_plan(source_plan, groups):
    refs = tuple(ref for batch in source_plan.classification_plan.batches for ref in batch.sources)
    indexed = {ref.id: ref for ref in refs}
    flattened = [sid for group in groups for sid in group.source_ids]
    if (len(flattened) != len(indexed) or len(flattened) != len(set(flattened)) or
            set(flattened) != set(indexed) or
            any(group.id != f'G{index}' or not group.source_ids or
                any(indexed[sid].content_digest != _digest(group.passage) for sid in group.source_ids)
                for index, group in enumerate(groups, 1)) or
            len({group.passage for group in groups}) != len(groups)):
        _fail('invalid_blind_group_inventory')
    order = {ref.id: index for index, ref in enumerate(refs)}
    if ([min(order[sid] for sid in group.source_ids) for group in groups] !=
            sorted(min(order[sid] for sid in group.source_ids) for group in groups) or
            any(tuple(sorted(group.source_ids, key=order.__getitem__)) != group.source_ids for group in groups)):
        _fail('invalid_blind_group_order')
    group_inventory = _digest([[group.id, group.source_ids, _digest(group.passage)] for group in groups])
    bindings = tuple(_digest({'stage': 'blind_assess_shard', 'source_binding': binding,
        'group_inventory': group_inventory,
        'group_ids': [group.id for group in groups if set(group.source_ids) <= set(source_ids)]})
        for source_ids, binding in zip(source_plan.shards, source_plan.adjudication_bindings))
    selection = _digest({'stage': 'select_after_blind_assessments',
        'source_selection_binding': source_plan.selection_binding, 'group_inventory': group_inventory,
        'adjudication_bindings': bindings})
    return BlindShardedPlan(source_plan, groups, bindings, selection,
        _digest({'source_plan': source_plan.plan_digest, 'group_inventory': group_inventory,
                 'adjudication_bindings': bindings, 'selection': selection}))


def freeze_blind_sharded_traversal(sources, input_revision, classifier_pin, adjudicator_pin,
                                  selector_pin, classification_options, adjudication_options,
                                  selection_options):
    source_plan = freeze_sharded_adjudicated_traversal(sources, input_revision, classifier_pin,
        adjudicator_pin, selector_pin, classification_options, adjudication_options, selection_options)
    return _blind_sharded_plan(source_plan, freeze_blind_source_groups(sources))


def verify_blind_sharded_traversal(plan, recorded_classifications, recorded_adjudications,
                                  recorded_selection):
    if not isinstance(plan, BlindShardedPlan):
        _fail('plan_invalid')
    try:
        rebuilt = _blind_sharded_plan(plan.source_plan, plan.groups)
    except (TypeError, AttributeError, ValueError):
        _fail('plan_mismatch')
    if rebuilt != plan:
        _fail('plan_mismatch')
    expected = [(index, binding) for index, (ids, binding) in
                enumerate(zip(plan.shards, plan.adjudication_bindings), 1) if ids]
    if not isinstance(recorded_adjudications, (list, tuple)) or len(recorded_adjudications) != len(expected):
        _fail('incomplete_adjudication_shards')
    for record, (index, binding) in zip(recorded_adjudications, expected):
        if (not isinstance(record, Mapping) or record.get('shard_index') != index or
                record.get('binding') != binding):
            _fail('blind_adjudication_binding_mismatch')
    if (not isinstance(recorded_selection, Mapping) or
            recorded_selection.get('binding') != plan.selection_binding or
            recorded_selection.get('adjudication_responses_digest') != _digest(recorded_adjudications)):
        _fail('blind_selection_binding_mismatch')
    underlying = [{**record, 'binding': plan.source_plan.adjudication_bindings[record['shard_index'] - 1]}
                  for record in recorded_adjudications]
    checked = verify_sharded_adjudicated_traversal(plan.source_plan, recorded_classifications, underlying,
        {**recorded_selection, 'binding': plan.source_plan.selection_binding,
         'adjudication_responses_digest': _digest(underlying)})
    return Verification(plan.plan_digest, checked.admitted_ids, checked.selected_ids)


def _direct_blind_plan(inventory, selector_pin, selection_options_json, groups, shards):
    # Validate exact group content/member order using the existing inventory guard.
    wrapper = _sharded_adjudicated_plan(inventory,
        {'name': inventory.model_name, 'digest': inventory.model_digest}, selector_pin,
        inventory.options_json, selection_options_json, shards)
    _blind_sharded_plan(wrapper, groups)
    group_inventory = _digest([[group.id, group.source_ids, _digest(group.passage)] for group in groups])
    context = {'inventory': inventory.inventory_digest, 'revision': inventory.input_revision,
        'assessor': [inventory.model_name, inventory.model_digest], 'assessment_options': inventory.options_json,
        'selector': [selector_pin['name'], selector_pin['digest']], 'selection_options': selection_options_json}
    bindings = tuple(_digest({'stage': 'direct_blind_assessment', 'index': index,
        'source_ids': ids, 'groups': group_inventory, 'context': context})
        for index, ids in enumerate(shards, 1))
    selection = _digest({'stage': 'select_after_direct_assessment', 'groups': group_inventory,
                        'assessment_bindings': bindings, 'context': context})
    return DirectBlindPlan(inventory, selector_pin['name'], selector_pin['digest'], selection_options_json,
        groups, shards, bindings, selection,
        _digest({'bindings': bindings, 'selection': selection, 'context': context}),
        sum(bool(ids) for ids in shards) + 1)


def freeze_direct_blind_traversal(sources, input_revision, assessor_pin, selector_pin,
                                 assessment_options, selection_options):
    if (not isinstance(selector_pin, Mapping) or set(selector_pin) != {'name', 'digest'} or
            not _text(selector_pin['name']) or not _text(selector_pin['digest']) or
            not isinstance(selection_options, Mapping)):
        _fail('bad_direct_model_options')
    inventory = freeze_traversal(sources, input_revision, assessor_pin, assessment_options)
    return _direct_blind_plan(inventory, selector_pin, _canon(dict(selection_options)),
                             freeze_blind_source_groups(sources), freeze_adjudication_shards(sources))


def verify_direct_blind_traversal(plan, recorded_assessments, recorded_selection):
    if not isinstance(plan, DirectBlindPlan):
        _fail('plan_invalid')
    base = plan.inventory_plan
    try:
        refs = tuple(ref for batch in base.batches for ref in batch.sources)
        inventory = _build(refs, base.input_revision, base.model_name, base.model_digest, base.options_json)
        rebuilt = _direct_blind_plan(inventory,
            {'name': plan.selector_model_name, 'digest': plan.selector_model_digest},
            plan.selection_options_json, plan.groups, plan.shards)
    except (TypeError, AttributeError, ValueError):
        _fail('plan_mismatch')
    if rebuilt != plan:
        _fail('plan_mismatch')
    expected = [(index, binding) for index, (ids, binding) in
                enumerate(zip(plan.shards, plan.assessment_bindings), 1) if ids]
    if not isinstance(recorded_assessments, (list, tuple)) or len(recorded_assessments) != len(expected):
        _fail('incomplete_direct_assessments')
    for record, (index, binding) in zip(recorded_assessments, expected):
        if (not isinstance(record, Mapping) or record.get('shard_index') != index or
                record.get('binding') != binding or record.get('inventory_digest') != base.inventory_digest or
                not _text(record.get('response_hash'))):
            _fail('direct_assessment_binding_mismatch')
    if (not isinstance(recorded_selection, Mapping) or recorded_selection.get('binding') != plan.selection_binding or
            recorded_selection.get('inventory_digest') != base.inventory_digest or
            recorded_selection.get('assessment_responses_digest') != _digest(recorded_assessments)):
        _fail('direct_selection_binding_mismatch')
    selected = recorded_selection.get('selected_ids')
    admitted = tuple(ref.id for ref in refs)
    if (not isinstance(selected, (list, tuple)) or len(selected) != len(set(selected)) or
            any(sid not in admitted for sid in selected)):
        _fail('unadmitted_direct_selection')
    return Verification(plan.plan_digest, admitted, tuple(selected))


def recorded_status_support(statuses, aliases, own_eid_map, allowed_by_alias, *, absent='not_present'):
    """Claude-authored generic projection, adapted to the required status object."""
    if set(statuses) != set(aliases):
        _fail('incomplete_recorded_topic_statuses')
    present = [(alias, value) for alias, value in statuses.items() if value != absent]
    if len(present) > 4:
        _fail('too_many_recorded_present_topics')
    result = {}
    for alias, ordinal in present:
        if ordinal not in own_eid_map or ordinal not in allowed_by_alias[alias]:
            _fail('unoffered_recorded_topic_evidence')
        result[aliases[alias]] = own_eid_map[ordinal]
    return result
