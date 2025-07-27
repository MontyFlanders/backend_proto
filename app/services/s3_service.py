import os
import boto3
from urllib.parse import urljoin
from datetime import datetime


class S3Service:
    def __init__(self):
        self.bucket = os.getenv("S3_BUCKET")
        self.region = os.getenv("S3_REGION", "us-east-1")
        self.expiry = int(os.getenv("S3_UPLOAD_EXPIRY_SECONDS", "300"))

        self.s3 = boto3.client(
            "s3",
            region_name=self.region,
            endpoint_url=os.getenv("S3_ENDPOINT"),  # Use None for AWS
            aws_access_key_id=os.getenv("S3_ACCESS_KEY"),
            aws_secret_access_key=os.getenv("S3_SECRET_KEY")
        )

    def generate_upload_url(self, filename: str, folder: str = "uploads") -> dict:
        """
        Returns a pre-signed URL and object key the client can use to upload a file directly.
        """
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        key = f"{folder}/{timestamp}_{filename}"

        url = self.s3.generate_presigned_url(
            ClientMethod="put_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=self.expiry
        )

        return {"url": url, "key": key}

    def get_object_url(self, key: str) -> str:
        """
        Returns a public URL to access the file, useful after upload.
        """
        if os.getenv("S3_ENDPOINT"): 
            return urljoin(f"{os.getenv('S3_ENDPOINT')}/{self.bucket}/", key)
        else:  # AWS
            return f"https://{self.bucket}.s3.amazonaws.com/{key}"

    def ensure_bucket_exists(self):
        """
        Useful on startup: create the bucket if it doesnt exist (dev only).
        """
        try:
            self.s3.head_bucket(Bucket=self.bucket)
        except self.s3.exceptions.ClientError:
            self.s3.create_bucket(Bucket=self.bucket)
            print(f"Created S3 bucket: {self.bucket}")
