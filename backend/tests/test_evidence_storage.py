import asyncio
import hashlib
from io import BytesIO

import pytest
from starlette.datastructures import UploadFile

from app.core.config import settings
from app.core.errors import PathEscapeError
from app.services import evidence_storage


def _enable_s3(monkeypatch):
    monkeypatch.setattr(settings, "s3_endpoint", "http://127.0.0.1:9000")
    monkeypatch.setattr(settings, "s3_access_key", "test")
    monkeypatch.setattr(settings, "s3_secret_key", "test")
    monkeypatch.setattr(settings, "s3_bucket", "geo-evidence")
    monkeypatch.setattr(settings, "s3_region", "us-east-1")
    monkeypatch.setattr(settings, "s3_secure", False)


def test_s3_requires_all_four_key_fields(monkeypatch):
    _enable_s3(monkeypatch)
    assert evidence_storage.s3_enabled() is True
    monkeypatch.setattr(settings, "s3_secret_key", "")
    assert evidence_storage.s3_enabled() is False


def test_s3_roundtrip_with_fake_client(monkeypatch):
    _enable_s3(monkeypatch)

    class FakeClient:
        def __init__(self):
            self.objects = {}

        def put_object(self, Bucket, Key, Body, ContentType):
            self.objects[(Bucket, Key)] = (Body, ContentType)

        def get_object(self, Bucket, Key):
            body, _ = self.objects[(Bucket, Key)]
            return {"Body": BytesIO(body)}

    fake = FakeClient()
    monkeypatch.setattr(evidence_storage, "_s3_client", lambda: fake)
    monkeypatch.setattr(evidence_storage, "_ensure_bucket", lambda client: None)

    payload = b"# s3 evidence\nline 2\n"
    upload = UploadFile(filename="evidence.md", file=BytesIO(payload))

    checksum, size = asyncio.run(
        evidence_storage.save_upload(upload, "evidence/p/s3.md", "text/markdown")
    )

    assert size == len(payload)
    assert checksum == hashlib.sha256(payload).hexdigest()
    assert evidence_storage.read_bytes("evidence/p/s3.md") == payload
    assert fake.objects[("geo-evidence", "evidence/p/s3.md")][1] == "text/markdown"


def test_storage_key_rejects_path_escape():
    with pytest.raises(PathEscapeError):
        evidence_storage.read_bytes("../etc/passwd")
