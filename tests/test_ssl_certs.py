import ssl

from core.ssl_certs import configure_ssl_certificates


def test_configure_ssl_certificates_sets_bundle(monkeypatch) -> None:
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)

    cafile = configure_ssl_certificates()
    assert cafile is not None
    assert cafile.endswith("cacert.pem")

    import os

    assert os.environ["SSL_CERT_FILE"] == cafile
    assert os.environ["REQUESTS_CA_BUNDLE"] == cafile

    ctx = ssl.create_default_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
