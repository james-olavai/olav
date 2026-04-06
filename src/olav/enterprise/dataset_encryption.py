from __future__ import annotations

import enum
import hashlib
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
import tink
from tink import aead, cleartext_keyset_handle


class EncryptionMode(enum.Enum):
    disabled = "disabled"
    optional = "optional"
    required = "required"


class TempFilePolicy(enum.Enum):
    memory_preferred = "memory_preferred"
    delete_on_success = "delete_on_success"
    keep_for_debug = "keep_for_debug"


def build_associated_data(
    export_id: str,
    format_name: str,
    dedup_strategy: str,
    scoring_policy: str,
    version: str = "v1",
) -> bytes:
    return f"{export_id}:{format_name}:{version}:{dedup_strategy}:{scoring_policy}".encode()


def atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


_AEAD_REGISTERED = False

_KMS_URI_PREFIXES = ("gcp-kms://", "aws-kms://", "hcvault://", "azure-kms://")


def is_kms_key_ref(key_ref: str) -> bool:
    return any(key_ref.startswith(prefix) for prefix in _KMS_URI_PREFIXES)


def _ensure_aead_registered() -> None:
    global _AEAD_REGISTERED
    if not _AEAD_REGISTERED:
        aead.register()
        _AEAD_REGISTERED = True


class DatasetEncryptor:
    def __init__(self, keyset_dir: Path | None = None):
        self._keyset_dir = keyset_dir or (Path.home() / ".olav" / "keys")
        self._keyset_handle: Any = None
        _ensure_aead_registered()

    @property
    def has_keyset(self) -> bool:
        return self._keyset_handle is not None

    def generate_keyset(self) -> None:
        self._keyset_handle = tink.new_keyset_handle(aead.aead_key_templates.AES128_GCM)

    def save_keyset(self, key_ref: str = "dataset-export-key-v1") -> Path:
        if self._keyset_handle is None:
            raise RuntimeError("No keyset loaded or generated")
        self._keyset_dir.mkdir(parents=True, exist_ok=True)
        path = self._keyset_dir / f"{key_ref}.json"
        with open(path, "w") as f:
            writer = tink.JsonKeysetWriter(f)
            cleartext_keyset_handle.write(writer, self._keyset_handle)
        return path

    def load_keyset(self, key_ref: str = "dataset-export-key-v1") -> None:
        if is_kms_key_ref(key_ref):
            self._load_kms_keyset(key_ref)
            return
        path = self._keyset_dir / f"{key_ref}.json"
        if not path.exists():
            raise FileNotFoundError(f"Keyset not found: {path}")
        raw = path.read_text(encoding="utf-8")
        reader = tink.JsonKeysetReader(raw)
        self._keyset_handle = cleartext_keyset_handle.read(reader)

    def _load_kms_keyset(self, key_ref: str) -> None:
        """Load a KMS-backed envelope keyset.

        Supports GCP KMS (``gcp-kms://``), AWS KMS (``aws-kms://``),
        HashiCorp Vault (``hcvault://``), and Azure Key Vault (``azure-kms://``).

        The envelope keyset JSON is stored locally in ``self._keyset_dir`` encrypted by
        the KMS key (envelope encryption).  On first call a new keyset is generated
        and wrapped by the KMS key; subsequent calls unwrap the stored keyset.

        Required extras per provider:
        - GCP:          ``pip install tink[gcpkms]``
        - AWS:          ``pip install tink[awskms]``
        - HashiCorp:    ``pip install tink[hcvaultkms]``
        - Azure:        ``pip install tink[azurekms]``
        """
        master_aead = self._build_kms_aead(key_ref)

        ref_digest = hashlib.sha256(key_ref.encode()).hexdigest()[:16]
        envelope_path = self._keyset_dir / f"kms-{ref_digest}.json"
        self._keyset_dir.mkdir(parents=True, exist_ok=True)

        if envelope_path.exists():
            raw = envelope_path.read_text(encoding="utf-8")
            reader = tink.JsonKeysetReader(raw)
            self._keyset_handle = tink.read_keyset_handle(reader, master_aead)
        else:
            self._keyset_handle = tink.new_keyset_handle(aead.aead_key_templates.AES128_GCM)
            with open(envelope_path, "w", encoding="utf-8") as f:
                writer = tink.JsonKeysetWriter(f)
                self._keyset_handle.write(writer, master_aead)

    @staticmethod
    def _build_kms_aead(key_ref: str) -> Any:
        """Return a Tink Aead backed by the KMS key identified by *key_ref*."""
        if key_ref.startswith("gcp-kms://"):
            try:
                from tink.integration import gcpkms
            except ImportError as exc:
                raise ImportError(
                    "GCP KMS support requires tink[gcpkms]: pip install tink[gcpkms]"
                ) from exc
            client = gcpkms.GcpKmsClient(key_uri=key_ref, credentials_path=None)
        elif key_ref.startswith("aws-kms://"):
            try:
                from tink.integration import awskms
            except ImportError as exc:
                raise ImportError(
                    "AWS KMS support requires tink[awskms]: pip install tink[awskms]"
                ) from exc
            client = awskms.AwsKmsClient(key_uri=key_ref, credentials_path=None)
        elif key_ref.startswith("hcvault://"):
            try:
                from tink.integration import hcvaultkms
            except ImportError as exc:
                raise ImportError(
                    "HashiCorp Vault KMS support requires tink[hcvaultkms]: "
                    "pip install tink[hcvaultkms]"
                ) from exc
            token = os.environ.get("VAULT_TOKEN", "")
            client = hcvaultkms.HcVaultKmsClient(uri_prefix=key_ref, token=token)
        elif key_ref.startswith("azure-kms://"):
            try:
                from tink.integration import azurekms
            except ImportError as exc:
                raise ImportError(
                    "Azure Key Vault support requires tink[azurekms]: "
                    "pip install tink[azurekms]"
                ) from exc
            client = azurekms.AzureKmsClient(key_uri=key_ref, credentials=None)
        else:
            raise ValueError(f"Unsupported KMS URI scheme in key_ref={key_ref!r}")

        return client.get_aead(key_ref)

    def encrypt_bytes(self, plaintext: bytes, associated_data: bytes) -> bytes:
        if self._keyset_handle is None:
            raise RuntimeError("No keyset loaded — call generate_keyset() or load_keyset() first")
        primitive = self._keyset_handle.primitive(aead.Aead)
        return primitive.encrypt(plaintext, associated_data)

    def decrypt_bytes(self, ciphertext: bytes, associated_data: bytes) -> bytes:
        if self._keyset_handle is None:
            raise RuntimeError("No keyset loaded — call generate_keyset() or load_keyset() first")
        primitive = self._keyset_handle.primitive(aead.Aead)
        return primitive.decrypt(ciphertext, associated_data)


def check_encryption_mode(mode: str, encrypt_flag: bool | None) -> bool:
    if mode == EncryptionMode.required.value:
        if encrypt_flag is False:
            raise ValueError("Cannot disable encryption in required mode")
        return True
    if mode == EncryptionMode.optional.value:
        return encrypt_flag is True
    return encrypt_flag is True


_TOKEN_AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS token_audit_log (
    event_id VARCHAR PRIMARY KEY,
    event_type VARCHAR NOT NULL,
    export_id VARCHAR NOT NULL,
    user_id VARCHAR,
    token_jti VARCHAR,
    ts TIMESTAMP NOT NULL,
    detail VARCHAR
)
"""

_TOKEN_DENYLIST_DDL = """
CREATE TABLE IF NOT EXISTS token_denylist (
    jti VARCHAR PRIMARY KEY,
    denied_at TIMESTAMP NOT NULL
)
"""


class OneTimeTokenManager:
    def __init__(self, secret: str, conn: Any | None = None):
        self._secret = secret
        self._conn = conn
        self._memory_denylist: set[str] = set()
        if self._conn is not None:
            self._conn.execute(_TOKEN_AUDIT_DDL)
            self._conn.execute(_TOKEN_DENYLIST_DDL)

    def _log_event(
        self,
        event_type: str,
        export_id: str,
        user_id: str | None,
        jti: str,
        detail: str | None = None,
    ) -> None:
        if self._conn is None:
            return
        self._conn.execute(
            "INSERT INTO token_audit_log (event_id, event_type, export_id, user_id, token_jti, ts, detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [str(uuid.uuid4()), event_type, export_id, user_id, jti, datetime.now(UTC), detail],
        )

    def _is_denied(self, jti: str) -> bool:
        if jti in self._memory_denylist:
            return True
        if self._conn is not None:
            row = self._conn.execute("SELECT 1 FROM token_denylist WHERE jti = ?", [jti]).fetchone()
            return row is not None
        return False

    def _deny(self, jti: str) -> None:
        self._memory_denylist.add(jti)
        if self._conn is not None:
            self._conn.execute(
                "INSERT OR IGNORE INTO token_denylist (jti, denied_at) VALUES (?, ?)",
                [jti, datetime.now(UTC)],
            )

    def issue(self, export_id: str, user_id: str, ttl_minutes: int = 10) -> dict[str, str]:
        jti = hashlib.sha256(uuid.uuid4().bytes).hexdigest()[:24]
        now = datetime.now(UTC)
        exp = now + timedelta(minutes=ttl_minutes)
        payload = {
            "export_id": export_id,
            "user_id": user_id,
            "jti": jti,
            "iat": now,
            "exp": exp,
        }
        token = jwt.encode(payload, self._secret, algorithm="HS256")
        self._log_event("token_issued", export_id, user_id, jti)
        return {
            "export_id": export_id,
            "access_mode": "one_time_token",
            "token": token,
            "expires_at": exp.isoformat(),
        }

    def verify(self, token: str, export_id: str) -> dict[str, Any]:
        try:
            claims = jwt.decode(token, self._secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError as exc:
            raise ValueError("Token has expired") from exc
        except jwt.InvalidTokenError as exc:
            raise ValueError("Invalid token") from exc

        jti = claims["jti"]

        if claims["export_id"] != export_id:
            self._log_event(
                "token_denied", export_id, claims.get("user_id"), jti, "export_id mismatch"
            )
            raise ValueError(
                f"export_id mismatch: token bound to {claims['export_id']!r}, got {export_id!r}"
            )

        if self._is_denied(jti):
            self._log_event("token_denied", export_id, claims.get("user_id"), jti, "already used")
            raise ValueError("Token has already been used")

        self._deny(jti)
        self._log_event("token_verified", export_id, claims.get("user_id"), jti)
        return claims
