import asyncio
import hashlib
from io import BytesIO

import pytest
from starlette.datastructures import UploadFile

from app.core.config import settings
from app.core.errors import AppError, PathEscapeError
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


def _client_error(code: str, status: int, operation: str = "HeadBucket"):
    from botocore.exceptions import ClientError

    return ClientError(
        {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        operation,
    )


class _BucketClient:
    def __init__(self, head_error=None, create_error=None):
        self.head_error = head_error
        self.create_error = create_error
        self.create_kwargs = None

    def head_bucket(self, Bucket):
        if self.head_error is not None:
            raise self.head_error
        return {}

    def create_bucket(self, **kwargs):
        self.create_kwargs = kwargs
        if self.create_error is not None:
            raise self.create_error
        return {}


def test_ensure_bucket_only_creates_when_head_returns_404(monkeypatch):
    _enable_s3(monkeypatch)
    fake = _BucketClient(head_error=_client_error("404", 404))
    evidence_storage._ensure_bucket(fake)
    assert fake.create_kwargs == {"Bucket": "geo-evidence"}


def test_ensure_bucket_403_does_not_create(monkeypatch):
    _enable_s3(monkeypatch)
    fake = _BucketClient(head_error=_client_error("AccessDenied", 403))
    with pytest.raises(AppError) as exc:
        evidence_storage._ensure_bucket(fake)
    assert exc.value.code == "evidence_storage_bucket_forbidden"
    assert fake.create_kwargs is None


def test_ensure_bucket_other_error_does_not_create(monkeypatch):
    _enable_s3(monkeypatch)
    fake = _BucketClient(head_error=_client_error("InternalError", 500))
    with pytest.raises(AppError) as exc:
        evidence_storage._ensure_bucket(fake)
    assert exc.value.code == "evidence_storage_bucket_check_failed"
    assert fake.create_kwargs is None


def test_ensure_bucket_handles_create_race(monkeypatch):
    _enable_s3(monkeypatch)
    fake = _BucketClient(
        head_error=_client_error("NoSuchBucket", 404),
        create_error=_client_error("BucketAlreadyOwnedByYou", 409, "CreateBucket"),
    )
    evidence_storage._ensure_bucket(fake)
    assert fake.create_kwargs == {"Bucket": "geo-evidence"}


def test_ensure_bucket_rejects_bucket_owned_by_another_account(monkeypatch):
    _enable_s3(monkeypatch)
    fake = _BucketClient(
        head_error=_client_error("NoSuchBucket", 404),
        create_error=_client_error("BucketAlreadyExists", 409, "CreateBucket"),
    )
    with pytest.raises(AppError) as exc:
        evidence_storage._ensure_bucket(fake)
    assert exc.value.code == "evidence_storage_bucket_unavailable"
