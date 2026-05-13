"""
Cloudflare R2 Client (S3-compatible via boto3).
"""
from __future__ import annotations
import boto3
from botocore.exceptions import ClientError


class R2Client:

    def __init__(self, account_id: str, access_key_id: str, secret_access_key: str, bucket: str):
        self.bucket = bucket
        self._s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    # ── Connection ─────────────────────────────────────────────────────────────

    def test_connection(self) -> tuple[bool, str]:
        try:
            self._s3.head_bucket(Bucket=self.bucket)
            return True, ""
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("403", "AccessDenied"):
                return False, "Zugriff verweigert (403). Access Key oder Permissions prüfen."
            if code == "404":
                return False, f"Bucket '{self.bucket}' nicht gefunden."
            return False, f"Fehler {code}: {e}"
        except Exception as e:
            return False, str(e)

    # ── List ───────────────────────────────────────────────────────────────────

    def list_files(self, prefix: str = "") -> tuple[bool, list[str] | str]:
        """
        Lists immediate children under prefix (like ls, not find).
        Returns (True, ["subfolder/", "file.mp4", ...]) relative to prefix.
        """
        try:
            clean = prefix.strip("/")
            q_prefix = (clean + "/") if clean else ""
            paginator = self._s3.get_paginator("list_objects_v2")
            items: list[str] = []
            for page in paginator.paginate(Bucket=self.bucket, Prefix=q_prefix, Delimiter="/"):
                for cp in page.get("CommonPrefixes") or []:
                    name = cp["Prefix"][len(q_prefix):].rstrip("/")
                    if name:
                        items.append(name + "/")
                for obj in page.get("Contents") or []:
                    name = obj["Key"][len(q_prefix):]
                    if name and "/" not in name:
                        items.append(name)
            items.sort(key=lambda x: (not x.endswith("/"), x.lower()))
            return True, items
        except ClientError as e:
            return False, f"{e.response['Error']['Code']}: {e}"
        except Exception as e:
            return False, str(e)

    # ── Download ───────────────────────────────────────────────────────────────

    def download_file(self, key: str, local_path: str) -> tuple[bool, str]:
        try:
            self._s3.download_file(self.bucket, key.lstrip("/"), local_path)
            return True, ""
        except ClientError as e:
            return False, f"{e.response['Error']['Code']}: {e}"
        except Exception as e:
            return False, str(e)

    # ── Upload ─────────────────────────────────────────────────────────────────

    def upload_string(self, content: str, key: str, encoding: str = "utf-8") -> tuple[bool, str]:
        try:
            self._s3.put_object(
                Bucket=self.bucket, Key=key.lstrip("/"),
                Body=content.encode(encoding),
                ContentType="application/json; charset=utf-8",
            )
            return True, ""
        except ClientError as e:
            return False, f"{e.response['Error']['Code']}: {e}"
        except Exception as e:
            return False, str(e)

    def upload_bytes(self, data: bytes, key: str,
                     content_type: str = "application/octet-stream") -> tuple[bool, str]:
        try:
            self._s3.put_object(
                Bucket=self.bucket, Key=key.lstrip("/"),
                Body=data, ContentType=content_type,
            )
            return True, ""
        except ClientError as e:
            return False, f"{e.response['Error']['Code']}: {e}"
        except Exception as e:
            return False, str(e)

    def upload_file(self, local_path: str, key: str) -> tuple[bool, str]:
        try:
            self._s3.upload_file(local_path, self.bucket, key.lstrip("/"))
            return True, ""
        except ClientError as e:
            return False, f"{e.response['Error']['Code']}: {e}"
        except Exception as e:
            return False, str(e)

    # ── Delete ─────────────────────────────────────────────────────────────────

    def delete_file(self, key: str) -> tuple[bool, str]:
        try:
            self._s3.delete_object(Bucket=self.bucket, Key=key.lstrip("/"))
            return True, ""
        except ClientError as e:
            return False, f"{e.response['Error']['Code']}: {e}"
        except Exception as e:
            return False, str(e)
