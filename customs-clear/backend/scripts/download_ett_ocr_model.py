#!/usr/bin/env python3
"""Download one pinned Russian OCR model into an explicit private directory.

No global installation, model execution, OCR or legal approval occurs here.
The upstream Git blob identity and exact size are pinned independently of HTTP.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.source_http import validate_body_headers


UPSTREAM_REPOSITORY = "tesseract-ocr/tessdata_fast"
UPSTREAM_COMMIT = "87416418657359cb625c412a48b6e1d6d41c29bd"
SOURCE_URL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/87416418657359cb625c412a48b6e1d6d41c29bd/rus.traineddata"
EXPECTED_GIT_BLOB_SHA1 = "b146cb2263acbc6383f8e92ea0ce759537687bb8"
EXPECTED_SIZE = 3_861_738
MAX_BYTES = 5 * 1024 * 1024
DEADLINE_SECONDS = 60
IO_TIMEOUT_SECONDS = 5
MODEL_FILENAME = "rus.traineddata"
RECEIPT_FILENAME = "receipt.json"
LICENSE_FILENAME = "LICENSE"
BUNDLED_LICENSE = Path(__file__).resolve().parent / "licenses" / "tessdata_fast-LICENSE"
LICENSE_SOURCE_URL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/87416418657359cb625c412a48b6e1d6d41c29bd/LICENSE"
LICENSE_SIZE = 11_358
LICENSE_GIT_BLOB_SHA1 = "d645695673349e3947e8e5ae42332d0ac3164cd7"
LICENSE_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"


class ModelDownloadError(ValueError):
    """A stable failure without transport secrets or response text."""


def verify_model_bytes(body: bytes) -> dict:
    if type(body) is not bytes or len(body) != EXPECTED_SIZE or len(body) > MAX_BYTES:
        raise ModelDownloadError("OCR model size does not match the upstream pin")
    blob_sha1 = hashlib.sha1(f"blob {len(body)}\0".encode("ascii") + body).hexdigest()
    if blob_sha1 != EXPECTED_GIT_BLOB_SHA1:
        raise ModelDownloadError("OCR model Git blob identity does not match the upstream pin")
    return {"size_bytes": len(body), "git_blob_sha1": blob_sha1, "sha256": hashlib.sha256(body).hexdigest()}


async def _fetch_model_bytes(*, transport=None) -> bytes:
    try:
        # The outer timeout cancels an entire slow/trickled response; each
        # individual network operation is also limited to five seconds.
        async with asyncio.timeout(DEADLINE_SECONDS):
            async with httpx.AsyncClient(
                transport=transport, trust_env=False, verify=True,
                follow_redirects=False, timeout=httpx.Timeout(IO_TIMEOUT_SECONDS),
                headers={"Accept": "application/octet-stream", "Accept-Encoding": "identity", "User-Agent": "Tariff-ETT-pinned-OCR-model/1"},
            ) as client:
                async with client.stream("GET", SOURCE_URL) as response:
                    if response.status_code != 200 or str(response.url) != SOURCE_URL:
                        raise ModelDownloadError("Pinned OCR model did not return HTTP 200 at its exact URL")
                    if "transfer-encoding" in response.headers and "content-length" in response.headers:
                        raise ModelDownloadError("OCR model response has ambiguous framing")
                    declared = validate_body_headers(response.headers, max_bytes=MAX_BYTES)
                    if declared is not None and declared != EXPECTED_SIZE:
                        raise ModelDownloadError("OCR model declared size does not match the upstream pin")
                    body = bytearray()
                    async for chunk in response.aiter_raw():
                        if len(body) + len(chunk) > MAX_BYTES:
                            raise ModelDownloadError("OCR model body exceeds its size limit")
                        body.extend(chunk)
                    if declared is not None and len(body) != declared:
                        raise ModelDownloadError("OCR model Content-Length does not match its body")
                    result = bytes(body)
                    verify_model_bytes(result)
                    return result
    except ModelDownloadError:
        raise
    except TimeoutError as exc:
        raise ModelDownloadError("OCR model download exceeded its deadline") from exc
    except (httpx.HTTPError, RuntimeError, OSError) as exc:
        raise ModelDownloadError("OCR model download failed") from exc


def fetch_model_bytes(*, transport=None) -> bytes:
    """The injected HTTP transport is a test seam; CLI uses normal verified TLS."""
    return asyncio.run(_fetch_model_bytes(transport=transport))


def _license_bytes() -> bytes:
    # Exact upstream LICENSE retained in the source tree at the same commit as
    # the model. Validate it before copying, without a second network request.
    with BUNDLED_LICENSE.open("rb") as source:
        body = source.read(LICENSE_SIZE + 1)
    if (len(body) != LICENSE_SIZE or hashlib.sha256(body).hexdigest() != LICENSE_SHA256
            or hashlib.sha1(f"blob {len(body)}\0".encode("ascii") + body).hexdigest() != LICENSE_GIT_BLOB_SHA1):
        raise ModelDownloadError("Bundled OCR model license does not match its upstream pin")
    return body


def _open_directory(path: Path, *, create: bool) -> int:
    if ".." in path.parts or "\x00" in str(path) or path == Path(path.anchor):
        raise ModelDownloadError("OCR model output directory is invalid")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(path.anchor, flags)
    try:
        for index, component in enumerate(path.parts[1:]):
            if create and index == len(path.parts) - 2:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            following = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        metadata = os.fstat(descriptor)
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise ModelDownloadError("OCR model output directory must be owned and private")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


@contextmanager
def _private_directory(path: Path):
    if os.name != "posix":
        raise ModelDownloadError("Private OCR model publication requires POSIX")
    import fcntl

    descriptor = _open_directory(path, create=True)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for name in (MODEL_FILENAME, RECEIPT_FILENAME, LICENSE_FILENAME):
            try:
                os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise ModelDownloadError("OCR model output files already exist")
        yield descriptor
    finally:
        os.close(descriptor)


def _publish_file(directory: int, name: str, body: bytes) -> None:
    temporary = ".ocr-model-" + secrets.token_hex(16)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        os.fsync(directory)
    finally:
        os.unlink(temporary, dir_fd=directory)


def download_model(output_directory: Path, *, transport=None) -> dict:
    path = Path(output_directory).absolute()
    license_body = _license_bytes()
    with _private_directory(path) as directory:
        body = fetch_model_bytes(transport=transport)
        verified = verify_model_bytes(body)
        # Resolve every ancestor again before publishing, without following a
        # replaced directory or a newly inserted symlink.
        current = _open_directory(path, create=False)
        try:
            old_stat, new_stat = os.fstat(directory), os.fstat(current)
            if (old_stat.st_dev, old_stat.st_ino) != (new_stat.st_dev, new_stat.st_ino):
                raise ModelDownloadError("OCR model output directory changed")
        finally:
            os.close(current)
        receipt = {
            "schema_version": 1, "kind": "pinned_ocr_model_download",
            "source_url": SOURCE_URL, "upstream_repository": UPSTREAM_REPOSITORY,
            "upstream_commit": UPSTREAM_COMMIT, "language": "rus",
            "model_filename": MODEL_FILENAME, "upstream_license": "Apache-2.0",
            "license": {"filename": LICENSE_FILENAME, "source_url": LICENSE_SOURCE_URL,
                        "size_bytes": LICENSE_SIZE, "git_blob_sha1": LICENSE_GIT_BLOB_SHA1,
                        "sha256": LICENSE_SHA256},
            "retrieved_at": datetime.now(timezone.utc).isoformat(), **verified,
            "git_blob_pin_verified": True, "model_executed": False,
            "installed_globally": False, "legal_approval": False,
            "usage": "ocr_candidate_generation_only",
        }
        receipt_bytes = (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode("utf-8")
        _publish_file(directory, LICENSE_FILENAME, license_body)
        _publish_file(directory, MODEL_FILENAME, body)
        _publish_file(directory, RECEIPT_FILENAME, receipt_bytes)
        return receipt


def main(argv=None, *, transport=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = download_model(args.output_directory, transport=transport)
    except Exception:
        print(json.dumps({"status": "ERROR", "reason": "model_download_or_publication_failed", "legal_approval": False}))
        return 2
    print(json.dumps({"status": "downloaded", **receipt}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
