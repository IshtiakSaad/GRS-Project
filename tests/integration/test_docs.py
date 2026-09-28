def test_openapi_schema_is_served(client):
    response = client.get("/api/schema/")
    assert response.status_code == 200
    assert b"openapi" in response.content


def test_swagger_ui_is_served(client):
    assert client.get("/api/docs/").status_code == 200
