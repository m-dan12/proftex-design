"""Единый обработчик 422: у любого роутера `detail` — строка, а не список pydantic."""

import pytest


@pytest.mark.parametrize(
    "url",
    [
        "/api/generations?scope=mine&limit=0",
        "/api/generations?scope=other",
        "/api/generations",
    ],
)
def test_query_errors_are_plain_text(client, login_as, user, url) -> None:
    login_as(user)
    response = client.get(url)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_body_error_is_plain_text(client, login_as, admin) -> None:
    login_as(admin)
    response = client.post("/api/admin/users", json={"username": "ab"})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
