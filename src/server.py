"""Bound the API process even on hosts without memory cgroup support."""

import os


def main():
    if os.name == "posix":
        import resource

        megabytes = int(os.environ.get("MAX_ADDRESS_SPACE_MB", "768"))
        if not 512 <= megabytes <= 1536:
            raise RuntimeError("MAX_ADDRESS_SPACE_MB must be between 512 and 1536")
        limit = megabytes * 1024 * 1024
        _, hard = resource.getrlimit(resource.RLIMIT_AS)
        if hard != resource.RLIM_INFINITY:
            limit = min(limit, hard)
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        workers=1,
        limit_concurrency=16,
        timeout_keep_alive=5,
        timeout_graceful_shutdown=80,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
