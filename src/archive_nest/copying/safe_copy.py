from __future__ import annotations

import os
from pathlib import Path

from archive_nest.cancellation import CancellationToken
from archive_nest.hashing import DEFAULT_CHUNK_SIZE, sha256_file


class CopyVerificationError(OSError):
    """Raised when a copied file cannot be verified safely."""


def copy_and_verify(
    source: Path,
    destination: Path,
    expected_sha256: str,
    *,
    session_id: str,
    cancellation: CancellationToken | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> None:
    token = cancellation or CancellationToken()
    before = source.stat()
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f"{destination.name}.{session_id}.partial")
    if destination.exists():
        raise FileExistsError(f"Destination already exists: {destination}")
    if partial.exists():
        partial.unlink()

    try:
        with source.open("rb") as input_stream, partial.open("xb") as output_stream:
            while chunk := input_stream.read(chunk_size):
                token.raise_if_cancelled()
                output_stream.write(chunk)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        after = source.stat()
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ino != after.st_ino
        ):
            raise CopyVerificationError("Source changed while it was being copied")
        copied_hash = sha256_file(partial, cancellation=token, chunk_size=chunk_size)
        if copied_hash != expected_sha256:
            raise CopyVerificationError(
                f"SHA-256 mismatch: expected {expected_sha256}, got {copied_hash}"
            )
        if destination.exists():
            raise FileExistsError(f"Destination appeared during copy: {destination}")
        partial.rename(destination)
    except Exception:
        # The partial is deliberately retained for diagnosis and resume handling.
        raise
