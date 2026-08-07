# -*- coding: utf-8 -*-
"""Tests for JWT auth and favorites endpoints."""
import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_headers(client):
    """Register a fresh user and return Authorization headers + user info."""
    import uuid

    suffix = uuid.uuid4().hex[:8]
    payload = {
        "username": f"testuser_{suffix}",
        "email": f"test_{suffix}@example.com",
        "password": "secret123",
    }
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    return headers, data["user"]


def test_register_login_me(client, auth_headers):
    headers, user = auth_headers
    assert user["username"].startswith("testuser_")
    assert user["email"].endswith("@example.com")

    # Login with the same credentials
    login_payload = {"email": user["email"], "password": "secret123"}
    resp = client.post("/api/auth/login", json=login_payload)
    assert resp.status_code == 200, resp.text
    login_data = resp.json()
    assert "access_token" in login_data

    # /me with token
    resp = client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200
    me_data = resp.json()
    assert me_data["_id"] == user["_id"]
    assert me_data["email"] == user["email"]
    assert "password_hash" not in me_data


def test_register_duplicate_email(client, auth_headers):
    _, user = auth_headers
    payload = {
        "username": "another_username",
        "email": user["email"],
        "password": "secret123",
    }
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 409


def test_login_wrong_password(client, auth_headers):
    _, user = auth_headers
    resp = client.post(
        "/api/auth/login",
        json={"email": user["email"], "password": "wrongpass"},
    )
    assert resp.status_code == 401


def test_me_without_token(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_favorites_crud(client, auth_headers):
    headers, _ = auth_headers

    # Initially empty
    resp = client.get("/api/favorites", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0

    # Add favorite
    fav_payload = {
        "product_url": "https://www.thegioididong.com/dtdd/xiaomi-poco-m8-8gb-256gb",
        "source": "Thế Giới Di Động",
        "name": "Xiaomi POCO M8 8GB/256GB",
        "image_url": "https://example.com/poco-m8.jpg",
        "price": "5.990.000₫",
    }
    resp = client.post("/api/favorites", json=fav_payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["added"] is True

    # Check is favorite
    resp = client.get(
        "/api/favorites/check",
        params={
            "product_url": fav_payload["product_url"],
            "source": fav_payload["source"],
        },
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["favorite"] is True

    # List favorites
    resp = client.get("/api/favorites", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["favorites"][0]["product_url"] == fav_payload["product_url"]

    # Adding duplicate returns added=False
    resp = client.post("/api/favorites", json=fav_payload, headers=headers)
    assert resp.json()["added"] is False
    assert data["total"] == 1 or client.get("/api/favorites", headers=headers).json()["total"] == 1

    # Remove favorite
    resp = client.delete(
        "/api/favorites",
        params={
            "product_url": fav_payload["product_url"],
            "source": fav_payload["source"],
        },
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["favorite"] is False

    # Check no longer favorite
    resp = client.get(
        "/api/favorites/check",
        params={
            "product_url": fav_payload["product_url"],
            "source": fav_payload["source"],
        },
        headers=headers,
    )
    assert resp.json()["favorite"] is False


def test_favorites_requires_auth(client):
    resp = client.get("/api/favorites")
    assert resp.status_code == 401