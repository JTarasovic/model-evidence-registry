"""``registry`` CLI — build the artifact from fixtures (default) or live sources.

    registry build --fixtures --out dist/     # deterministic, no network (PoC default)
    registry build --live --out dist/         # hit real public sources (best-effort smoke)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from registry.build import DEFAULT_GLOBAL_CONCURRENCY, build, fixture_transport
from registry.connectors import credentialed_connectors, default_connectors
from registry.publish import publish

DEFAULT_FIXTURES = Path(__file__).resolve().parent.parent.parent / "fixtures"


def _live_transport():  # pragma: no cover - network path, not exercised in CI
    import httpx

    class HttpxTransport:
        def __init__(self) -> None:
            self._client = httpx.Client(timeout=30.0, follow_redirects=True)

        def request(self, url: str, headers: dict[str, str], *, timeout_seconds: float | None = None):
            from registry.fetch import RawResponse

            resp = self._client.get(url, headers=headers, timeout=timeout_seconds)
            return RawResponse(
                status=resp.status_code,
                body=resp.content,
                etag=resp.headers.get("etag"),
                last_modified=resp.headers.get("last-modified"),
            )

    return HttpxTransport()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="registry")
    sub = parser.add_subparsers(dest="command", required=True)
    build_cmd = sub.add_parser("build", help="build the model-evidence artifact")
    mode = build_cmd.add_mutually_exclusive_group()
    mode.add_argument("--fixtures", action="store_true", default=True, help="build from saved fixtures (default)")
    mode.add_argument("--live", action="store_true", help="fetch live public sources")
    build_cmd.add_argument("--out", type=Path, default=Path("dist"), help="output directory")
    build_cmd.add_argument("--fixtures-dir", type=Path, default=DEFAULT_FIXTURES)
    build_cmd.add_argument(
        "--global-concurrency",
        type=int,
        default=DEFAULT_GLOBAL_CONCURRENCY,
        help=f"maximum in-flight source requests (default: {DEFAULT_GLOBAL_CONCURRENCY})",
    )

    args = parser.parse_args(argv)
    if args.command != "build":
        parser.error("unknown command")
    if args.global_concurrency < 1:
        parser.error("--global-concurrency must be at least 1")

    connectors = default_connectors()
    if args.live:
        # Credentialed sources join only on a live build and only when their key is present — the
        # fixture build stays a fixed, public-only set (credentialed_connectors() self-gates on env).
        connectors = connectors + credentialed_connectors()
        transport = _live_transport()
    else:
        transport = fixture_transport(args.fixtures_dir, connectors)

    result = build(connectors, transport, global_concurrency=args.global_concurrency)
    manifest = publish(result, args.out)
    print(f"wrote {len(result.artifact.records)} records to {args.out}/")
    for source in manifest["sources"]:
        print(f"  - {source['source_id']}: {source['fetch_outcome']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
