"""AWS S3 access (ADR-013). All keys are firm-prefixed; the bucket is private."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import boto3
from botocore.config import Config

from dam.config import get_settings


@lru_cache
def s3_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        region_name=settings.s3_region,
        endpoint_url=settings.s3_endpoint_url,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"} if settings.s3_endpoint_url else {},
        ),
    )


def original_key(firm_id: uuid.UUID, asset_id: uuid.UUID, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"firms/{firm_id}/originals/{asset_id}/original.{ext}"


def derived_key(firm_id: uuid.UUID, asset_id: uuid.UUID, variant: str, ext: str) -> str:
    return f"firms/{firm_id}/derived/{asset_id}/{variant}.{ext}"


@dataclass
class MultipartSession:
    upload_id: str
    part_size: int
    part_count: int
    part_urls: list[str]


def start_multipart(key: str, mime: str, size: int) -> MultipartSession:
    settings = get_settings()
    client = s3_client()
    upload_id = client.create_multipart_upload(Bucket=settings.s3_bucket, Key=key, ContentType=mime)[
        "UploadId"
    ]
    part_size = settings.multipart_part_size
    part_count = max(1, -(-size // part_size))
    urls = [
        client.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": settings.s3_bucket,
                "Key": key,
                "UploadId": upload_id,
                "PartNumber": n,
            },
            ExpiresIn=6 * 3600,
        )
        for n in range(1, part_count + 1)
    ]
    return MultipartSession(upload_id, part_size, part_count, urls)


def complete_multipart(key: str, upload_id: str, parts: list[dict]) -> None:
    s3_client().complete_multipart_upload(
        Bucket=get_settings().s3_bucket,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={
            "Parts": [
                {"ETag": p["etag"], "PartNumber": p["part_number"]}
                for p in sorted(parts, key=lambda p: p["part_number"])
            ]
        },
    )


def abort_multipart(key: str, upload_id: str) -> None:
    s3_client().abort_multipart_upload(Bucket=get_settings().s3_bucket, Key=key, UploadId=upload_id)


def head(key: str) -> dict | None:
    try:
        return s3_client().head_object(Bucket=get_settings().s3_bucket, Key=key)
    except s3_client().exceptions.ClientError as e:  # pragma: no cover - network path
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def get_bytes(key: str) -> bytes:
    return s3_client().get_object(Bucket=get_settings().s3_bucket, Key=key)["Body"].read()


def download_to(key: str, path: str) -> None:
    s3_client().download_file(get_settings().s3_bucket, key, path)


def put_bytes(key: str, data: bytes, mime: str) -> None:
    s3_client().put_object(Bucket=get_settings().s3_bucket, Key=key, Body=data, ContentType=mime)


def put_file(key: str, path: str, mime: str) -> None:
    s3_client().upload_file(path, get_settings().s3_bucket, key, ExtraArgs={"ContentType": mime})


def delete_prefix(prefix: str) -> None:
    settings = get_settings()
    client = s3_client()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=prefix):
        objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if objs:
            client.delete_objects(Bucket=settings.s3_bucket, Delete={"Objects": objs})


def presigned_get(key: str, *, filename: str | None = None) -> str:
    settings = get_settings()
    params: dict = {"Bucket": settings.s3_bucket, "Key": key}
    if filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
    return s3_client().generate_presigned_url(
        "get_object", Params=params, ExpiresIn=settings.presign_ttl_seconds
    )


def derived_url(key: str) -> str:
    """Derived files go through CloudFront when configured, else a presigned S3 URL."""
    settings = get_settings()
    if settings.cloudfront_domain and settings.cloudfront_key_id:
        return _cloudfront_signed_url(f"https://{settings.cloudfront_domain}/{key}")
    return presigned_get(key)


@lru_cache
def _cloudfront_signer():
    from botocore.signers import CloudFrontSigner
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    settings = get_settings()
    assert settings.cloudfront_private_key_path
    with open(settings.cloudfront_private_key_path, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)

    def rsa_signer(message: bytes) -> bytes:
        return key.sign(message, padding.PKCS1v15(), hashes.SHA1())  # CloudFront requires SHA1

    return CloudFrontSigner(settings.cloudfront_key_id, rsa_signer)


def _cloudfront_signed_url(url: str) -> str:
    expires = datetime.now(UTC) + timedelta(seconds=get_settings().presign_ttl_seconds)
    return _cloudfront_signer().generate_presigned_url(url, date_less_than=expires)
