"""Каркас из T01: каждая операция контракта смонтирована в приложении, и ничего лишнего."""

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from openapi_spec_validator import validate

from app.main import app

ROOT = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((ROOT / "contracts" / "openapi.yaml").read_text(encoding="utf-8"))
METHODS = {"get", "post", "put", "patch", "delete"}
OPERATIONS = [
    (method.upper(), path)
    for path, item in SPEC["paths"].items()
    for method in item
    if method in METHODS
]


def test_spec_is_valid() -> None:
    validate(SPEC)


def test_operation_count() -> None:
    assert len(OPERATIONS) == 19


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_operation_is_mounted(method: str, path: str) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    response = client.request(method, path.replace("{id}", "1"))
    assert response.status_code not in (404, 405), response.text


def test_no_routes_outside_contract() -> None:
    contract = set(OPERATIONS)
    mounted = {
        (method.upper(), path)
        for path, item in app.openapi()["paths"].items()
        for method in item
        if method in METHODS
    }
    assert mounted == contract
