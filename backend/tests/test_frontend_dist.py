"""Бэкенд отдаёт собранный фронтенд и не перекрывает `/api`."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def web(tmp_path: Path, env) -> TestClient:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>spa</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    env.setenv("FRONTEND_DIST", str(dist))
    with TestClient(create_app()) as client:
        yield client


def test_root_and_spa_routes_return_index(web: TestClient) -> None:
    for path in ("/", "/gallery", "/admin/users"):
        response = web.get(path)
        assert response.status_code == 200
        assert "<title>spa</title>" in response.text


def test_assets_are_served(web: TestClient) -> None:
    assert web.get("/assets/app.js").text == "console.log(1)"
    assert web.get("/assets/missing.js").status_code == 404


def test_api_is_not_shadowed(web: TestClient) -> None:
    assert web.get("/api/health").json()["mode"] == "mock"
    assert web.get("/api/unknown").status_code == 404


def test_path_traversal_is_blocked(web: TestClient) -> None:
    response = web.get("/..%2f..%2fetc/passwd")
    assert "root:" not in response.text


def test_dotdot_paths_are_not_spa_fallback(web: TestClient) -> None:
    for path in ("/api/generations/..%2f..%2fetc%2fpasswd/image", "/assets/..%2f..%2fetc%2fpasswd"):
        assert web.get(path).status_code == 404
