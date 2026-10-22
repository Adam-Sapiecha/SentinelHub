from time import monotonic

import requests


def read_limited(response: requests.Response, limit: int = 4 * 1024 * 1024) -> bytes:
    """Bound decompressed upstream data, not just its advertised Content-Length."""
    chunks = []
    total = 0
    started = monotonic()
    try:
        for chunk in response.iter_content(65536):
            if monotonic() - started > 65:
                raise requests.Timeout("Przekroczono czas odczytu usługi")
            total += len(chunk)
            if total > limit:
                raise ValueError("Odpowiedź usługi przekracza limit 4 MiB")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        response.close()
