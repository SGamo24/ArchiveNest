from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO, Callable

from archive_nest.cancellation import CancellationToken

DEFAULT_CHUNK_SIZE = 1024 * 1024


def sha256_stream(
    stream: BinaryIO,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    cancellation: CancellationToken | None = None,
    on_chunk: Callable[[int], None] | None = None,
) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(chunk_size):
        if cancellation:
            cancellation.raise_if_cancelled()
        digest.update(chunk)
        if on_chunk:
            on_chunk(len(chunk))
    return digest.hexdigest()


def sha256_file(
    path: Path,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    cancellation: CancellationToken | None = None,
) -> str:
    with path.open("rb") as stream:
        return sha256_stream(stream, chunk_size=chunk_size, cancellation=cancellation)

