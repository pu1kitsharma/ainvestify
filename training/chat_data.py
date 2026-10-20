"""Chat-format SFT examples with explicit role tags (pure Python, no ML imports).

Each adapter role (author / QC / MD reviewer) has its own system tag and its own
dataset. A dataset mixes no roles: the QLoRA script and the MLX runner both reject
rows whose tag differs from the adapter being trained.
"""
import json
import re

ROLES = {
    'author': 'You are the analyst who drafts the requested banking work product.',
    'qc': 'You are the quality-control reviewer. List defects in the supplied work.',
    'md_reviewer': 'You are the managing-director reviewer. Decide what must change before release.',
}
_TAG = re.compile(r'^\[ROLE:([a-z_]+)\]')
OUTPUT_RULE = ('Reply with one JSON object only: {"observations": {<check>: {"status": "observed", '
               '"value": <value>}}}. Do not add commentary.')


def role_tag(role):
    if role not in ROLES:
        raise ValueError('Unknown adapter role: %r' % (role,))
    return '[ROLE:%s]' % role


def build_prompt(role, task_input):
    """System + user messages offered to the model. Never contains an answer key."""
    if not isinstance(task_input, dict):
        raise ValueError('Task input must be an object')
    system = '%s %s %s' % (role_tag(role), ROLES[role], OUTPUT_RULE)
    user = json.dumps(task_input, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]


def to_example(role, task_input, response_text):
    if not isinstance(response_text, str) or not response_text.strip():
        raise ValueError('Assistant response must be nonempty text')
    return {'messages': build_prompt(role, task_input) + [{'role': 'assistant', 'content': response_text}]}


def example_role(example):
    messages = example.get('messages') if isinstance(example, dict) else None
    if not isinstance(messages, list) or len(messages) < 3:
        raise ValueError('Example needs system, user and assistant messages')
    if [m.get('role') for m in messages[:2]] != ['system', 'user'] or messages[-1].get('role') != 'assistant':
        raise ValueError('Example message roles must start system,user and end assistant')
    for m in messages:
        if not isinstance(m.get('content'), str) or not m['content'].strip():
            raise ValueError('Empty message content')
    match = _TAG.match(messages[0]['content'])
    if not match or match.group(1) not in ROLES:
        raise ValueError('Missing or unknown role tag')
    return match.group(1)


def validate_dataset(examples, role):
    if role not in ROLES:
        raise ValueError('Unknown adapter role: %r' % (role,))
    if not examples:
        raise ValueError('Empty dataset')
    for example in examples:
        if example_role(example) != role:
            raise ValueError('Dataset row role differs from adapter role %r' % role)
    return len(examples)


def read_jsonl(path):
    rows = []
    with open(path, encoding='utf-8') as handle:
        for number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except ValueError as exc:
                    raise ValueError('%s line %d: invalid JSON' % (path, number)) from exc
    return rows


def parse_prediction(text, case_id, environment):
    """Extract the first JSON object holding `observations`; anything else yields
    an empty observation set (scored as missing, never repaired by code)."""
    observations = {}
    if isinstance(text, str):
        decoder = json.JSONDecoder()
        for start in (i for i, c in enumerate(text) if c == '{'):
            try:
                value, _ = decoder.raw_decode(text[start:])
            except ValueError:
                continue
            if isinstance(value, dict) and isinstance(value.get('observations'), dict):
                observations = value['observations']
                break
    return {'case_id': case_id, 'environment': environment, 'observations': observations}
