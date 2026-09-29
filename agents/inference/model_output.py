"""Parse an entire model JSON response without changing its contents."""
import json
import re


def json_body(raw):
    text = raw.strip()
    fenced = re.fullmatch(r'```(?:json)?\s*\n([\s\S]*?)\n```', text, re.IGNORECASE)
    if fenced:return fenced.group(1)
    # A missing presentation fence is not truncated JSON. Accept only a whole
    # parseable JSON value after that opening fence; never repair its contents
    # or take a substring from commentary/partial data.
    opening=re.match(r'^```(?:json)?\s*\n',text,re.IGNORECASE)
    if opening:
        candidate=text[opening.end():]
        try:json.loads(candidate)
        except ValueError:return text
        return candidate
    return text


def decode_model_object(raw):
    # A sole Markdown code fence is presentation, not a different answer.
    # Never extract a convenient JSON substring from surrounding commentary.
    return json.loads(json_body(raw))
