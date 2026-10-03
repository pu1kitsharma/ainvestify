"""Provider-neutral boundary for drafts derived exclusively from public facts."""
import json


class PublicEvidenceModel:
    combined_draft = True
    public_only = True
    thinking = False
    shared_review_thinking = None
    native_structured_output = False

    def __init__(self):
        self.last_route = {}
        self.last_response_text = ''
        self._public_context = None

    def set_public_context(self, company, facts):
        from agents.preparation.preparation_sources import inference_facts, is_public_source
        if not facts or not all(is_public_source(fact) for fact in facts):
            raise ValueError('Remote preparation requires collected public website evidence only.')
        self._public_context = {'company': company, 'facts': inference_facts(facts)}

    def _check_payload(self, evidence):
        data = json.loads(evidence)
        allowed = {'company','request','facts','previous_work','answer_to_correct','correction_required','sections'}
        if (not self._public_context or not isinstance(data, dict) or not set(data) <= allowed
                or data.get('request') not in ({}, '', None)
                or any(data.get(key) != value for key,value in self._public_context.items())):
            raise ValueError('The remote drafting payload differs from its approved public evidence. Private context was not sent.')
