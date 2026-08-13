"""Configure trusted CA certificates for HTTPS/WebSocket clients on macOS."""

from __future__ import annotations

import os
import ssl


def configure_ssl_certificates() -> str | None:
    """Point Python SSL and common HTTP clients at certifi's CA bundle.

    python.org builds on macOS ship without system roots linked, which breaks
    Deepgram (and other cloud APIs) with CERTIFICATE_VERIFY_FAILED.
    """
    try:
        import certifi
    except ImportError:
        return None

    cafile = certifi.where()
    os.environ.setdefault("SSL_CERT_FILE", cafile)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", cafile)

    def _default_context() -> ssl.SSLContext:
        return ssl.create_default_context(cafile=cafile)

    ssl._create_default_https_context = _default_context  # type: ignore[attr-defined]
    return cafile
