from src.auth_service.tokens import create_mock_jwt


def test_create_mock_jwt():
    token = create_mock_jwt({"sub": "user123"})
    assert token.startswith("eyJ")
    assert "mock_sig" in token
