import pytest
from django.core.management import call_command
from drf_spectacular.generators import SchemaGenerator

from apps.service_requests.serializers import ACTION_INPUTS


@pytest.fixture(scope="module")
def schema():
    return SchemaGenerator().get_schema(request=None, public=True)


def test_openapi_schema_is_served(client):
    response = client.get("/api/schema/")
    assert response.status_code == 200
    assert b"openapi" in response.content


def test_swagger_ui_is_served(client):
    assert client.get("/api/docs/").status_code == 200


def test_the_schema_is_valid_and_has_no_warnings(tmp_path):
    # A warning means a type the docs guessed (usually "string"): fail instead of shipping it.
    call_command("spectacular", "--validate", "--fail-on-warn", "--file", tmp_path / "s.yaml")


def test_swagger_can_log_in(schema):
    """Without a security scheme, Swagger UI has no Authorize button and a reader cannot
    try any endpoint past login."""
    scheme = schema["components"]["securitySchemes"]["bearerAuth"]
    assert (scheme["type"], scheme["scheme"]) == ("http", "bearer")
    assert {"bearerAuth": []} in schema["paths"]["/api/v1/requests"]["get"]["security"]
    assert "security" not in schema["paths"]["/api/v1/auth/login"]["post"]


def test_actions_are_listed_with_their_bodies(schema):
    operation = schema["paths"]["/api/v1/requests/{request_id}/actions/{action}"]["post"]
    action = next(p for p in operation["parameters"] if p["name"] == "action")
    assert action["schema"]["enum"] == sorted(ACTION_INPUTS)
    body = operation["requestBody"]["content"]["application/json"]["schema"]
    assert body == {"$ref": "#/components/schemas/ActionInRequest"}
    documented = {
        ref["$ref"].rsplit("/", 1)[1]
        for ref in schema["components"]["schemas"]["ActionInRequest"]["oneOf"]
    }
    with_fields = {f"{s.__name__}Request" for s in ACTION_INPUTS.values() if s().fields}
    assert documented == with_fields  # `start` takes no body, so it has no schema of its own
    for name in ACTION_INPUTS:
        assert f"`{name}`" in operation["description"]


def test_error_codes_are_documented(schema):
    operation = schema["paths"]["/api/v1/requests/{request_id}/actions/{action}"]["post"]
    responses = operation["responses"]
    for status, code in [
        ("401", "NOT_AUTHENTICATED"),
        ("404", "NOT_FOUND"),
        ("409", "INVALID_TRANSITION"),
        ("409", "POSSIBLE_DUPLICATE"),
        ("422", "IDEMPOTENCY_KEY_REUSED"),
    ]:
        assert f"`{code}`" in responses[status]["description"], (status, code)
    examples = responses["409"]["content"]["application/json"]["examples"].values()
    assert "POSSIBLE_DUPLICATE" in {e["value"]["error"]["code"] for e in examples}
    login = schema["paths"]["/api/v1/auth/login"]["post"]["responses"]
    assert "`LOGIN_DELAYED`" in login["429"]["description"]
