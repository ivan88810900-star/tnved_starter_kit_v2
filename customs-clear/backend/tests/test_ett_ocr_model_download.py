"""Offline transport and private-publication checks for the pinned OCR model."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import stat

import httpx
import pytest

from scripts import download_ett_ocr_model as model


BODY = b"synthetic-test-model-not-executable"


class Chunks(httpx.AsyncByteStream):
    def __init__(self, *chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


def transport(body=BODY, *, status=200, headers=None):
    def handler(request):
        assert str(request.url) == model.SOURCE_URL
        assert request.method == "GET"
        assert request.headers["accept-encoding"] == "identity"
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        return httpx.Response(status, headers=headers or {}, stream=Chunks(body))
    return httpx.MockTransport(handler)


@pytest.fixture
def fixture_pin(monkeypatch):
    monkeypatch.setattr(model, "EXPECTED_SIZE", len(BODY))
    monkeypatch.setattr(model, "EXPECTED_GIT_BLOB_SHA1", hashlib.sha1(f"blob {len(BODY)}\0".encode() + BODY).hexdigest())


def test_real_upstream_identity_is_pinned():
    assert model.UPSTREAM_COMMIT == "87416418657359cb625c412a48b6e1d6d41c29bd"
    assert model.EXPECTED_GIT_BLOB_SHA1 == "b146cb2263acbc6383f8e92ea0ce759537687bb8"
    assert model.EXPECTED_SIZE == 3861738
    assert model.SOURCE_URL == "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/87416418657359cb625c412a48b6e1d6d41c29bd/rus.traineddata"
    assert model.DEADLINE_SECONDS == 60
    assert model.IO_TIMEOUT_SECONDS == 5


def test_exact_model_is_published_privately_without_installation(fixture_pin, tmp_path):
    output = tmp_path / "russian-model"
    report = model.download_model(output, transport=transport(headers={"Content-Length": str(len(BODY))}))
    assert (output / "rus.traineddata").read_bytes() == BODY
    assert json.loads((output / "receipt.json").read_text()) == report
    assert report["git_blob_pin_verified"] is True
    assert report["sha256"] == hashlib.sha256(BODY).hexdigest()
    assert report["model_executed"] is False
    assert report["installed_globally"] is False
    assert report["legal_approval"] is False
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in output.iterdir())
    assert sorted(p.name for p in output.iterdir()) == ["LICENSE", "receipt.json", "rus.traineddata"]
    assert (output / "LICENSE").read_bytes() == model.BUNDLED_LICENSE.read_bytes()
    assert report["license"]["sha256"] == model.LICENSE_SHA256


def test_existing_private_directory_can_be_used(fixture_pin, tmp_path):
    output = tmp_path / "russian-model"
    output.mkdir(mode=0o700)
    assert model.download_model(output, transport=transport())["git_blob_pin_verified"]


@pytest.mark.parametrize("body", [b"", BODY + b"x", BODY[:-1]])
def test_wrong_body_size_fails_without_publishing(fixture_pin, tmp_path, body):
    output = tmp_path / "model"
    with pytest.raises(model.ModelDownloadError, match="size"):
        model.download_model(output, transport=transport(body))
    assert list(output.iterdir()) == []


def test_same_size_wrong_git_blob_fails(fixture_pin, tmp_path):
    with pytest.raises(model.ModelDownloadError, match="Git blob identity"):
        model.download_model(tmp_path / "model", transport=transport(b"X" * len(BODY)))


def test_git_blob_digest_includes_object_header(fixture_pin):
    assert model.verify_model_bytes(BODY)["git_blob_sha1"] != hashlib.sha1(BODY).hexdigest()


@pytest.mark.parametrize("headers", [
    {"Content-Length": "0"}, {"Content-Length": "99999999"},
    {"Content-Length": "not-a-number"}, {"Content-Encoding": "gzip"},
    {"Content-Encoding": "br"},
    {"Content-Length": str(len(BODY)), "Transfer-Encoding": "chunked"},
])
def test_bad_headers_fail_before_publication(fixture_pin, tmp_path, headers):
    with pytest.raises(model.ModelDownloadError):
        model.download_model(tmp_path / "model", transport=transport(headers=headers))
    assert list((tmp_path / "model").iterdir()) == []


@pytest.mark.parametrize("status,location", [(301, model.SOURCE_URL), (302, "https://evil.invalid/model"), (307, "https://raw.githubusercontent.com/unpinned/model"), (404, "")])
def test_redirects_and_non_200_are_never_followed(fixture_pin, tmp_path, status, location):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(status, headers={"Location": location}, stream=Chunks(BODY))
    with pytest.raises(model.ModelDownloadError, match="HTTP 200"):
        model.download_model(tmp_path / "model", transport=httpx.MockTransport(handler))
    assert calls == [model.SOURCE_URL]


def test_unknown_size_body_is_stream_bounded(fixture_pin, monkeypatch):
    monkeypatch.setattr(model, "MAX_BYTES", 10)
    with pytest.raises(model.ModelDownloadError, match="size limit"):
        model.fetch_model_bytes(transport=transport(b"a" * 11))


def test_response_trickle_is_cancelled_by_outer_deadline(fixture_pin, monkeypatch):
    monkeypatch.setattr(model, "DEADLINE_SECONDS", 0.02)
    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(1)
            yield BODY
    t = httpx.MockTransport(lambda request: httpx.Response(200, stream=Slow()))
    with pytest.raises(model.ModelDownloadError, match="deadline"):
        model.fetch_model_bytes(transport=t)


def test_network_error_is_sanitized(fixture_pin):
    def failed(request):
        raise httpx.ConnectError("secret credentials from an unsafe exception", request=request)
    with pytest.raises(model.ModelDownloadError) as caught:
        model.fetch_model_bytes(transport=httpx.MockTransport(failed))
    assert "secret" not in str(caught.value)


def test_transport_ignores_environment_proxy_and_auth(fixture_pin, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "https://secret:password@evil.invalid")
    original = model.httpx.AsyncClient
    observed = {}
    def client(**kwargs):
        observed.update(kwargs)
        return original(**kwargs)
    monkeypatch.setattr(model.httpx, "AsyncClient", client)
    assert model.fetch_model_bytes(transport=transport()) == BODY
    assert observed["trust_env"] is False
    assert observed["verify"] is True
    assert observed["follow_redirects"] is False
    assert "auth" not in observed and "proxy" not in observed and "cookies" not in observed
    assert observed["timeout"].read == 5


@pytest.mark.parametrize("name", ["rus.traineddata", "receipt.json", "LICENSE"])
def test_existing_outputs_are_not_overwritten_or_downloaded(fixture_pin, tmp_path, monkeypatch, name):
    output = tmp_path / "model"
    output.mkdir(mode=0o700)
    (output / name).write_bytes(b"existing")
    monkeypatch.setattr(model, "fetch_model_bytes", lambda **k: pytest.fail("must not download"))
    with pytest.raises(model.ModelDownloadError, match="already exist"):
        model.download_model(output)
    assert (output / name).read_bytes() == b"existing"


def test_unsafe_directory_permissions_are_not_silently_changed(fixture_pin, tmp_path):
    output = tmp_path / "model"
    output.mkdir(mode=0o755)
    with pytest.raises(model.ModelDownloadError, match="private"):
        model.download_model(output, transport=transport())
    assert stat.S_IMODE(output.stat().st_mode) == 0o755


@pytest.mark.parametrize("at_root", [True, False])
def test_directory_symlinks_are_rejected(fixture_pin, tmp_path, at_root):
    target = tmp_path / "actual"
    target.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    output = link if at_root else link / "child"
    with pytest.raises(OSError):
        model.download_model(output, transport=transport())
    assert list(target.iterdir()) == []


def test_dangling_output_symlink_is_not_overwritten(fixture_pin, tmp_path):
    output = tmp_path / "model"
    output.mkdir(mode=0o700)
    (output / "rus.traineddata").symlink_to(tmp_path / "missing")
    with pytest.raises(model.ModelDownloadError, match="already exist"):
        model.download_model(output, transport=transport())
    assert (output / "rus.traineddata").is_symlink()


def test_replaced_root_is_detected_before_publication(fixture_pin, tmp_path, monkeypatch):
    output = tmp_path / "model"
    def replacement(**kwargs):
        output.rename(tmp_path / "original")
        output.mkdir(mode=0o700)
        return BODY
    monkeypatch.setattr(model, "fetch_model_bytes", replacement)
    with pytest.raises(model.ModelDownloadError, match="directory changed"):
        model.download_model(output)
    assert list(output.iterdir()) == list((tmp_path / "original").iterdir()) == []


def test_cli_returns_reviewable_receipt_and_sanitized_failure(fixture_pin, tmp_path, capsys):
    output = tmp_path / "model"
    assert model.main(["--output-directory", str(output)], transport=transport()) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "downloaded"
    assert model.main(["--output-directory", str(output)], transport=transport()) == 2
    error = json.loads(capsys.readouterr().out)
    assert error == {"status": "ERROR", "reason": "model_download_or_publication_failed", "legal_approval": False}


def test_global_install_directories_are_not_created(fixture_pin, tmp_path):
    parent = tmp_path / "missing-parent"
    with pytest.raises(FileNotFoundError):
        model.download_model(parent / "model", transport=transport())
    assert not parent.exists()


def test_upstream_license_exact_bytes_are_retained():
    body = model._license_bytes()
    assert len(body) == 11358
    assert hashlib.sha256(body).hexdigest() == "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
    assert b"Apache License" in body


def test_altered_license_prevents_download_and_publication(fixture_pin, tmp_path, monkeypatch):
    license_path = tmp_path / "altered-license"
    license_path.write_bytes(b"wrong license")
    monkeypatch.setattr(model, "BUNDLED_LICENSE", license_path)
    monkeypatch.setattr(model, "fetch_model_bytes", lambda **k: pytest.fail("must not download"))
    with pytest.raises(model.ModelDownloadError, match="license"):
        model.download_model(tmp_path / "model")
    assert not (tmp_path / "model").exists()
