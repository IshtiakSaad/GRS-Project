"""Attachments against the real object store: the presigned URLs, the upload and the checks all
run as they do in production."""

import hashlib
import urllib.error
import urllib.request
from datetime import timedelta

import pytest
from botocore.exceptions import BotoCoreError
from django.conf import settings
from django.test import override_settings

from apps.audit.models import AuditLog
from apps.collab import storage, verification
from apps.collab.models import Attachment, AttachmentStatus
from apps.collab.scanning import EICAR, ScannerUnavailable
from apps.service_requests.models import Status

from ..auth.helpers import error_code
from ..requests.helpers import cast, in_state, key

pytestmark = pytest.mark.django_db

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 120
PDF = b"%PDF-1.4\n" + b"1 0 obj << >> endobj\n" * 10


@pytest.fixture(autouse=True)
def bucket():
    client = storage.internal()
    names = [b["Name"] for b in client.list_buckets()["Buckets"]]
    if settings.S3_BUCKET not in names:
        client.create_bucket(Bucket=settings.S3_BUCKET)


def _create(api, request, content: bytes, content_type: str, name="certificate.png", **headers):
    headers.setdefault("HTTP_IDEMPOTENCY_KEY", key())
    return api.post(
        f"/api/v1/requests/{request.public_id}/attachments",
        {"file_name": name, "content_type": content_type, "size": len(content)},
        format="json",
        **headers,
    )


def _put(upload: dict, content: bytes) -> int:
    # The body's real length, as any HTTP client sends it; the signature fixes the declared one.
    headers = {**upload["headers"], "Content-Length": str(len(content))}
    req = urllib.request.Request(upload["url"], data=content, method="PUT", headers=headers)
    try:
        return urllib.request.urlopen(req, timeout=10).status
    except urllib.error.HTTPError as exc:
        return exc.code


def _uploaded(api, request, content=PNG, content_type="image/png", sent=None) -> Attachment:
    """Create, upload (`sent` if given, else `content`), confirm and verify."""
    created = _create(api, request, content, content_type)
    assert created.status_code == 201, created.content
    body = created.json()
    assert _put(body["upload"], sent if sent is not None else content) == 200
    confirmed = api.post(f"/api/v1/attachments/{body['id']}/confirm")
    assert confirmed.status_code == 202
    assert confirmed.json()["status"] == AttachmentStatus.VERIFYING
    attachment = Attachment.objects.get(public_id=body["id"])
    verification.verify(attachment.pk)
    attachment.refresh_from_db()
    return attachment


def test_upload_check_and_download(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    api = as_user(c.owner)
    attachment = _uploaded(api, request)

    assert attachment.status == AttachmentStatus.READY
    assert attachment.sha256 == hashlib.sha256(PNG).hexdigest()
    assert (attachment.size_bytes, attachment.detected_content_type) == (len(PNG), "image/png")

    link = api.get(f"/api/v1/attachments/{attachment.public_id}/download")
    assert link.status_code == 200
    with urllib.request.urlopen(link.json()["url"], timeout=10) as response:
        assert response.read() == PNG
        assert response.headers["Content-Disposition"].startswith("attachment;")

    timeline = api.get(f"/api/v1/requests/{request.public_id}/timeline").json()
    assert timeline[-1]["type"] == "attachment_added"
    assert AuditLog.objects.filter(action="attachment.ready", target_id=attachment.pk).exists()


def test_the_store_refuses_a_body_of_another_size(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    created = _create(as_user(c.owner), request, PNG, "image/png").json()
    assert _put(created["upload"], PNG + b"extra") == 403  # the size is in the signature


def test_the_type_comes_from_the_bytes_not_the_label(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    api = as_user(c.owner)
    # Declared a PDF, sent a PNG of the same length.
    disguised = PNG[: len(PNG)]
    attachment = _uploaded(api, request, content=disguised, content_type="application/pdf")
    assert (attachment.status, attachment.rejection_reason) == ("REJECTED", "TYPE_MISMATCH")
    assert storage.size_of(attachment.storage_key) is None  # deleted from the store
    link = api.get(f"/api/v1/attachments/{attachment.public_id}/download")
    assert error_code(link) == "ATTACHMENT_NOT_READY"


def test_the_scanner_rejects_malware_even_disguised_as_a_pdf(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    attachment = _uploaded(as_user(c.owner), request, EICAR, "application/pdf")
    assert (attachment.status, attachment.rejection_reason) == ("REJECTED", "MALWARE")
    assert AuditLog.objects.filter(action="attachment.rejected", target_id=attachment.pk).exists()


def test_a_confirmed_file_that_never_arrived_is_rejected(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    api = as_user(c.owner)
    created = _create(api, request, PNG, "image/png").json()
    api.post(f"/api/v1/attachments/{created['id']}/confirm")
    attachment = Attachment.objects.get(public_id=created["id"])
    verification.verify(attachment.pk)
    attachment.refresh_from_db()
    assert attachment.rejection_reason == "NOT_UPLOADED"


def test_only_pdf_jpeg_and_png_up_to_10_mb(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    api = as_user(c.owner)
    url = f"/api/v1/requests/{request.public_id}/attachments"
    zipped = api.post(
        url,
        {"file_name": "a.zip", "content_type": "application/zip", "size": 10},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key(),
    )
    assert "content_type" in zipped.json()["error"]["fields"]
    huge = api.post(
        url,
        {"file_name": "a.pdf", "content_type": "application/pdf", "size": 10 * 1024 * 1024 + 1},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key(),
    )
    assert "size" in huge.json()["error"]["fields"]


def test_creating_is_idempotent(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    api = as_user(c.owner)
    k = key()
    first = _create(api, request, PNG, "image/png", HTTP_IDEMPOTENCY_KEY=k)
    again = _create(api, request, PNG, "image/png", HTTP_IDEMPOTENCY_KEY=k)
    assert again.json() == first.json()
    assert again["Idempotent-Replayed"] == "true"
    assert Attachment.objects.filter(request=request).count() == 1


def test_closed_requests_take_no_files(as_user):
    c = cast()
    request = in_state(c, Status.WITHDRAWN)
    assert error_code(_create(as_user(c.owner), request, PNG, "image/png")) == "REQUEST_CLOSED"


def test_a_draft_can_carry_files(as_user):
    c = cast()
    draft = in_state(c, Status.DRAFT)
    assert _create(as_user(c.owner), draft, PNG, "image/png").status_code == 201


@pytest.mark.parametrize(
    ("who", "code"), [("stranger", 404), ("outsider", 404), ("colleague", 200)]
)
def test_files_are_scoped(as_user, who, code):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    attachment = _uploaded(as_user(c.owner), request)
    api = as_user(c.by_name(who))
    assert api.get(f"/api/v1/attachments/{attachment.public_id}").status_code == code
    assert api.get(f"/api/v1/attachments/{attachment.public_id}/download").status_code == code
    assert api.get(f"/api/v1/requests/{request.public_id}/attachments").status_code == code


def test_only_the_uploader_confirms(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    created = _create(as_user(c.owner), request, PNG, "image/png").json()
    response = as_user(c.colleague).post(f"/api/v1/attachments/{created['id']}/confirm")
    assert response.status_code == 404


def test_upload_links_work_while_storage_is_down(as_user):
    """Signing is local: a storage outage does not stop a citizen attaching a file."""
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    with override_settings(S3_PUBLIC_ENDPOINT="http://127.0.0.1:9"):
        assert _create(as_user(c.owner), request, PNG, "image/png").status_code == 201


def test_verification_retries_while_storage_is_down(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    api = as_user(c.owner)
    created = _create(api, request, PNG, "image/png").json()
    api.post(f"/api/v1/attachments/{created['id']}/confirm")
    attachment = Attachment.objects.get(public_id=created["id"])
    with override_settings(S3_ENDPOINT="http://127.0.0.1:9"), pytest.raises(BotoCoreError):
        verification.verify(attachment.pk)  # the task's autoretry takes it from here
    attachment.refresh_from_db()
    assert attachment.status == AttachmentStatus.VERIFYING


@override_settings(
    ATTACHMENT_SCANNER="apps.collab.scanning.ClamdScanner", CLAMD_HOST="127.0.0.1", CLAMD_PORT=9
)
def test_a_file_waits_while_the_scanner_is_down(as_user):
    """No verdict, no approval: the file stays unverified and undownloadable, and the task's
    autoretry (then the sweep) scans it once the scanner is back."""
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    api = as_user(c.owner)
    created = _create(api, request, PNG, "image/png").json()
    assert _put(created["upload"], PNG) == 200
    api.post(f"/api/v1/attachments/{created['id']}/confirm")
    attachment = Attachment.objects.get(public_id=created["id"])
    with pytest.raises(ScannerUnavailable):
        verification.verify(attachment.pk)
    attachment.refresh_from_db()
    assert attachment.status == AttachmentStatus.VERIFYING
    link = api.get(f"/api/v1/attachments/{attachment.public_id}/download")
    assert error_code(link) == "ATTACHMENT_NOT_READY"


def test_stuck_verifications_are_swept(as_user):
    c = cast()
    request = in_state(c, Status.SUBMITTED)
    api = as_user(c.owner)
    created = _create(api, request, PNG, "image/png").json()
    api.post(f"/api/v1/attachments/{created['id']}/confirm")
    attachment = Attachment.objects.get(public_id=created["id"])
    assert verification.stuck() == []
    Attachment.objects.filter(pk=attachment.pk).update(
        created_at=attachment.created_at - timedelta(minutes=11)
    )
    assert verification.stuck() == [attachment.pk]
