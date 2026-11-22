"""Streaming a 2xx body to disk for ``fetch(stream_to=...)`` (#261).

Shared by the httpx and curl_cffi tiers. The body is written to a temp file in the
target's own directory and moved onto the target with :func:`os.replace` only after
the transfer completed with at least one byte, so the target path never holds a
partial download: a failed or empty transfer leaves it absent, or as it was.
"""

import hashlib
import os
import secrets
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from pathlib import Path

from polyfetch_scrape._backends import is_suspected_soft_block
from polyfetch_scrape.errors import FetchError

_EXCERPT_BYTES = 2048  # matches bounded_diagnostics' cap; more would be dropped anyway


def read_excerpt(chunks: Iterable[bytes]) -> bytes:
    """Read only the head of a streamed error body, for bounded diagnostics."""
    buf = bytearray()
    for chunk in chunks:
        buf += chunk
        if len(buf) >= _EXCERPT_BYTES:
            break
    return bytes(buf[:_EXCERPT_BYTES])


def save_streamed_body(
    method: str,
    status: int,
    content_type: str | None,
    chunks: Iterable[bytes],
    target: Path,
    url: str,
) -> tuple[int, str] | None:
    """Stream a 2xx body to ``target``; return ``(size, sha256 hex)``.

    ``None`` means the empty body is a suspected soft block (#237), which the caller
    turns into tier escalation exactly as for a buffered body. Any other empty body
    raises ``FetchError``: there is nothing to save. Errors raised by ``chunks``
    (transport errors, a deadline) propagate unchanged after the temp file is removed,
    so the caller can retry them as it does for a buffered transfer.
    """
    size, digest = _write_atomically(chunks, target)
    if size:
        return size, digest
    if is_suspected_soft_block(method, status, b"", content_type):
        return None
    raise FetchError(f"empty {status} body, nothing saved to {target}: {url}", status=status)


def _write_atomically(chunks: Iterable[bytes], target: Path) -> tuple[int, str]:
    tmp_path = target.with_name(f".{target.name}.{secrets.token_hex(6)}.part")
    size = 0
    digest = hashlib.sha256()
    with _disk_errors(f"creating a temp file beside {target}"):
        # "xb" (never an existing file) and the process umask, so the saved file gets the
        # same mode a plain write would; mkstemp would leave it 0600.
        fh = tmp_path.open("xb")
    try:
        try:
            for chunk in chunks:
                with _disk_errors(f"writing {target}"):
                    fh.write(chunk)
                size += len(chunk)
                digest.update(chunk)
            if size:
                with _disk_errors(f"flushing the download for {target}"):
                    fh.flush()
                    os.fsync(fh.fileno())  # data on disk before the rename publishes it
        finally:
            with _disk_errors(f"writing {target}"):
                fh.close()
        if size:
            # Same directory as the target, so this is an atomic rename on one filesystem.
            # A symlinked target is itself replaced by the new regular file; its referent
            # is left untouched.
            with _disk_errors(f"moving the download onto {target}"):
                os.replace(tmp_path, target)
    finally:
        with _disk_errors(f"removing the temp file {tmp_path}"):
            tmp_path.unlink(missing_ok=True)
    return size, digest.hexdigest()


@contextmanager
def _disk_errors(action: str) -> Generator[None]:
    """A local disk failure is a ``FetchError``, never retried as a transport error.

    Reason: wrapped around file operations only, never around reading the next chunk,
    because curl_cffi's transport errors subclass ``OSError`` too.
    """
    try:
        yield
    except OSError as exc:
        raise FetchError(f"{action} failed: {exc}") from exc
