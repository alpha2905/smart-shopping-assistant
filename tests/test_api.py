# tests/test_api.py
from fastapi.testclient import TestClient
import pytest
from main import app

client = TestClient(app)

def test_search_endpoint_requires_query():
    """
    Tests that the /api/search endpoint returns a 422 Unprocessable Entity
    error if the 'q' query parameter is missing.
    """
    response = client.get("/api/search")
    assert response.status_code == 422

def test_chat_endpoint_empty_message():
    """
    Tests the chatbot's response to an empty message.
    """
    response = client.post("/api/chat", json={"message": " "})
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "empty"
    assert "Bạn chưa nhập tin nhắn" in data["text"]