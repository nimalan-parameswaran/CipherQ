import httpx
import pytest

from backend.app.services import gemma


def test_accepts_only_local_loopback_endpoint():
    assert gemma._is_loopback_url("http://127.0.0.1:8081/v1/chat/completions")
    assert gemma._is_loopback_url("http://localhost:8081/v1/chat/completions")
    assert not gemma._is_loopback_url("https://127.0.0.1:8081/v1/chat/completions")
    assert not gemma._is_loopback_url("http://example.com:8081/v1/chat/completions")
    assert not gemma._is_loopback_url("http://127.0.0.1:9000/v1/chat/completions")


@pytest.mark.asyncio
async def test_empty_evidence_skips_model_call(monkeypatch):
    async def unexpected_client(*args, **kwargs):
        raise AssertionError("Model must not be called without evidence")

    monkeypatch.setattr(gemma.httpx, "AsyncClient", unexpected_client)

    result = await gemma.generate_grounded_answer("What is this?", [])
    assert result is None


@pytest.mark.asyncio
async def test_external_endpoint_is_rejected(monkeypatch):
    monkeypatch.setattr(gemma, "GEMMA_URL", "http://example.com:8081/v1/chat/completions")

    result = await gemma.generate_grounded_answer(
        "What does the document say?",
        [("notes.txt", 1, "The local server stores encrypted files.")],
    )
    assert result is None


@pytest.mark.asyncio
async def test_successful_local_generation(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [
                    {"message": {"content": "Files are stored in encrypted form."}}
                ]
            }

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_options"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json):
            captured["url"] = url
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(gemma.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(
        gemma, "GEMMA_URL", "http://127.0.0.1:8081/v1/chat/completions"
    )

    answer = await gemma.generate_grounded_answer(
        "How are files stored?",
        [("notes.txt", 2, "<b>Files</b> are stored in encrypted form.")],
    )

    assert answer == "Files are stored in encrypted form."
    assert captured["url"].startswith("http://127.0.0.1:8081/")
    assert captured["client_options"]["trust_env"] is False
    assert captured["payload"]["stream"] is False
    assert "Files are stored in encrypted form." in captured["payload"]["messages"][1]["content"]
    assert "<b>" not in captured["payload"]["messages"][1]["content"]


@pytest.mark.asyncio
async def test_model_http_error_uses_fallback(monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json):
            request = httpx.Request("POST", url)
            response = httpx.Response(503, request=request)
            raise httpx.HTTPStatusError(
                "Model unavailable", request=request, response=response
            )

    monkeypatch.setattr(gemma.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(
        gemma, "GEMMA_URL", "http://127.0.0.1:8081/v1/chat/completions"
    )

    answer = await gemma.generate_grounded_answer(
        "What does the document say?",
        [("notes.txt", 1, "The local server stores encrypted files.")],
    )
    assert answer is None
