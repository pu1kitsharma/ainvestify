"""Private deal names do not become public lookup queries by default."""
from agents.core import research_agent


def test_private_deal_research_skips_all_external_connectors(monkeypatch):
    def outbound(*args, **kwargs):
        raise AssertionError('Private company name left the room')

    for name in ('fetch_github_signal', 'fetch_hn_mentions', 'fetch_edgar_mentions', 'fetch_wikipedia_summary'):
        monkeypatch.setattr(research_agent, name, outbound)
    assert research_agent.research_deal('tenant', 'deal', 'Confidential Venture') == []


def test_verified_public_identity_enables_bounded_public_connectors(monkeypatch):
    calls = []

    def observed(*args):
        calls.append(args[-1])
        return []

    for name in ('fetch_github_signal', 'fetch_hn_mentions', 'fetch_edgar_mentions', 'fetch_wikipedia_summary'):
        monkeypatch.setattr(research_agent, name, observed)
    research_agent.research_deal('tenant', 'deal', 'Public Company', public_identity=True)
    assert calls == ['Public Company'] * 4
