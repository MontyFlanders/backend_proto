import os
from datetime import datetime
from typing import Dict

import boto3


class S3Service:
    """
    Small helper around S3 for generating presigned URLs.

    - In production: relies on IAM role + AWS_REGION (or S3_REGION).
    - Optionally supports custom S3_ENDPOINT / ACCESS_KEY / SECRET_KEY for dev.
    """

    def __init__(self) -> None:
        self.bucket = os.getenv("S3_BUCKET")
        if not self.bucket:
            raise ValueError("S3_BUCKET env var must be set")

        # Prefer explicit S3_REGION, fall back to AWS_REGION (what ECS/Lambda set)
        self.region = (
            os.getenv("S3_REGION")
            or os.getenv("AWS_REGION")
            or "us-west-2"
        )

        # Default 5 minutes
        self.expiry = int(os.getenv("S3_UPLOAD_EXPIRY_SECONDS", "300"))

        endpoint = os.getenv("S3_ENDPOINT")
        access_key = os.getenv("S3_ACCESS_KEY")
        secret_key = os.getenv("S3_SECRET_KEY")

        client_kwargs = {
            "service_name": "s3",
            "region_name": self.region,
        }

        # Optional: custom endpoint (MinIO / LocalStack)
        if endpoint:
            client_kwargs["endpoint_url"] = endpoint

        # Optional: explicit credentials (mostly for local dev)
        if access_key and secret_key:
            client_kwargs["aws_access_key_id"] = access_key
            client_kwargs["aws_secret_access_key"] = secret_key
        # In AWS prod, leave these unset and let IAM role take over.

        self.s3 = boto3.client(**client_kwargs)

    async def generate_upload_url(self, filename: str, folder: str = "uploads") -> Dict[str, str]:
        """
        Returns a pre-signed URL and object key the client can use to upload a file directly.

        This is 'async' for compatibility with the rest of the async API, but
        generate_presigned_url itself is CPU-only and non-blocking (no network I/O).
        """
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        key = f"{folder}/{timestamp}_{filename}"

        url = self.s3.generate_presigned_url(
            ClientMethod="put_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=self.expiry,
        )

        return {"url": url, "key": key}

    async def generate_download_url(self, key: str) -> str:
        """
        Returns a time-limited pre-signed URL to download a private object.

        Use this in production instead of exposing a public bucket.
        """
        url = self.s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=self.expiry,
        )
        return url

    def get_public_url(self, key: str) -> str:
        """
        Returns a *public* URL IF your bucket/objects are publicly readable.

        In your CDK config you’re using BlockPublicAccess.BLOCK_ALL, so this is
        mainly useful for dev or if you later front S3 via CloudFront / change policies.
        """
        endpoint = os.getenv("S3_ENDPOINT")
        if endpoint:
            # Custom endpoint style: http://endpoint/bucket/key
            endpoint = endpoint.rstrip("/")
            return f"{endpoint}/{self.bucket}/{key}"

        # Region-specific S3 URL
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"