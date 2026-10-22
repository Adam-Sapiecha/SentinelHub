import pytest

from src.core.config import get_public_url


def test_public_url_accepts_proxy_prefix(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://demo.example:8443/sentinelhub/")
    assert get_public_url() == "https://demo.example:8443/sentinelhub"


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@demo.example/app",
        "https://demo.example/../admin",
        "https://demo.example/app?key=secret",
        "https://demo.example/app#fragment",
        "http://demo.example/app",
        "https://demo.example/%2e%2e/admin",
    ],
)
def test_public_url_rejects_unsafe_configuration(monkeypatch, url):
    monkeypatch.setenv("PUBLIC_URL", url)
    with pytest.raises(RuntimeError):
        get_public_url()
