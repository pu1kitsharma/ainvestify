import pytest
from pydantic import BaseModel

from agents.inference.subscription_model import default_preparation_name, make_preparation_model
from agents.research.public_research import PublicResearchModel
from agents.inference.subscription_model import ClaudeProModel
from agents.preparation.authored_discovery import source_companies


def test_public_product_model_has_no_claude_transport_inheritance():
    assert not issubclass(PublicResearchModel, ClaudeProModel)


@pytest.mark.parametrize("provider", ["claude_pro_public", "anthropic_api_public", "deepseek_public"])
def test_retired_provider_configuration_fails_before_model_call(monkeypatch, provider):
    monkeypatch.setenv("PREPARATION_PROVIDER", provider)
    with pytest.raises(ValueError, match="local"):
        default_preparation_name()
    with pytest.raises(ValueError, match="local"):
        make_preparation_model("phi4-mini")
    with pytest.raises(ValueError, match="local"):
        PublicResearchModel()


@pytest.mark.parametrize("selection", ["claude-pro-sonnet", "anthropic-api:test", "deepseek-api:test"])
def test_retired_explicit_selection_fails(monkeypatch, selection):
    monkeypatch.setenv("PREPARATION_PROVIDER", "local")
    with pytest.raises(ValueError, match="retired"):
        make_preparation_model(selection)


def test_public_research_answer_uses_local_adapter(monkeypatch):
    class Answer(BaseModel):
        text: str

    def forbidden(*args, **kwargs):
        raise AssertionError("Hosted transport was called")

    monkeypatch.setenv("PREPARATION_PROVIDER", "local")
    monkeypatch.setattr("agents.inference.anthropic_api.run_api", forbidden)
    monkeypatch.setattr("agents.inference.deepseek_api.run_public", forbidden)
    monkeypatch.setattr("agents.inference.subscription_model.ClaudeProModel._run_cli", forbidden)
    calls = []

    def local_generate(self, instruction, evidence, schema):
        calls.append((instruction, evidence))
        self.last_response_text = '{"text":"locally generated"}'
        self.last_call = {"provider": "local"}
        return schema.model_validate_json(self.last_response_text)

    monkeypatch.setattr("agents.inference.local_models.LocalModel.generate", local_generate)
    model = PublicResearchModel()
    payload = {"public_request": "Indian seed companies", "geography": "India",
               "as_of": "2026-10-01", "pages": [], "max_companies": 1}
    import json
    model.approve("public_discovery", payload)
    answer = model.generate_for_task("public_discovery", "Use evidence", json.dumps(payload), Answer)
    assert answer.text == "locally generated"
    assert model.last_route == {"provider": "local"}
    assert len(calls) == 1


@pytest.mark.parametrize("provider", ["claude_pro_public", "anthropic_api_public", "deepseek_public"])
def test_production_discovery_rejects_retired_provider_before_side_effects(monkeypatch, provider):
    monkeypatch.setenv("PREPARATION_PROVIDER", provider)

    class ForbiddenStore:
        def __getattr__(self, name):
            raise AssertionError(f"Discovery touched storage before rejecting provider: {name}")

    with pytest.raises(ValueError, match="Only local model responses"):
        source_companies(ForbiddenStore(), object())


@pytest.mark.parametrize("provider", ["claude_pro_public", "anthropic_api_public", "deepseek_public"])
def test_discovery_http_route_cannot_use_hosted_model_when_misconfigured(monkeypatch, tmp_path, provider):
    from fastapi.testclient import TestClient
    from api.main import app
    from api import deps
    from store import Store

    monkeypatch.setenv("PREPARATION_PROVIDER", provider)
    monkeypatch.setenv("SOURCING_MODEL", "phi4-mini")
    invoked = []

    def forbidden(*args, **kwargs):
        invoked.append(True)
        raise AssertionError("Hosted inference was invoked")

    monkeypatch.setattr("agents.inference.deepseek_api.run_public", forbidden)
    monkeypatch.setattr("agents.inference.anthropic_api.run_api", forbidden)
    monkeypatch.setattr("agents.inference.subscription_model.ClaudeProModel._run_cli", forbidden)

    def get_store():
        with Store(tmp_path / "routes.db") as store:
            yield store

    prior = app.dependency_overrides.copy()
    app.dependency_overrides[deps.get_store] = get_store
    app.dependency_overrides[deps.get_tenant_id] = lambda: "tenant-test"
    try:
        with TestClient(app) as client:
            response = client.post("/api/leads/web-runs", json={"thesis": "Indian seed software companies", "geography": "India"})
            assert response.status_code == 202
            saved = client.get("/api/leads/web-runs/" + response.json()["id"])
            assert saved.status_code == 200
            assert saved.json()["status"] == "failed"
            assert saved.json()["company_ids"] == []
            assert invoked == []
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(prior)
