"""Tests for ada.x509util (X.509 / VOMS proxy expiry parsing).

Uses hand-built minimal DER fixtures rather than real certificates, so
no personal data (name/e-mail in a real cert's subject) ends up in the
repository. Structure was cross-checked against a real VOMS proxy with
``openssl asn1parse`` during development.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ada.exceptions import AdaAuthError
from ada.x509util import (
    VOMS_EXTENSION_OID,
    find_extension,
    pem_certs,
    voms_ac_validity,
    x509_validity,
)

# ---- Minimal DER encoder (test-only) ----

TAG_UTCTIME = 0x17
TAG_GENERALIZEDTIME = 0x18


def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _der_len(len(value)) + value


def _seq(*children: bytes) -> bytes:
    return _tlv(0x30, b"".join(children))


def _oid(dotted: str) -> bytes:
    parts = [int(p) for p in dotted.split(".")]
    out = bytes([parts[0] * 40 + parts[1]])
    for p in parts[2:]:
        chunks = [p & 0x7F]
        p >>= 7
        while p:
            chunks.insert(0, (p & 0x7F) | 0x80)
            p >>= 7
        out += bytes(chunks)
    return _tlv(0x06, out)


def _time(tag: int, dt: datetime) -> bytes:
    fmt = "%y%m%d%H%M%SZ" if tag == TAG_UTCTIME else "%Y%m%d%H%M%SZ"
    return _tlv(tag, dt.strftime(fmt).encode("ascii"))


def _int(value: int) -> bytes:
    b = value.to_bytes((value.bit_length() + 7) // 8 or 1, "big")
    if b[0] & 0x80:
        b = b"\x00" + b
    return _tlv(0x02, b)


def _octet_string(value: bytes) -> bytes:
    return _tlv(0x04, value)


def _context(tag_num: int, value: bytes) -> bytes:
    return _tlv(0x80 | 0x20 | tag_num, value)  # constructed, context-specific


def _build_cert(
    not_before: datetime,
    not_after: datetime,
    time_tag: int = TAG_UTCTIME,
    voms_ext_content: bytes | None = None,
) -> bytes:
    """Build a minimal, syntactically valid (but not cryptographically
    meaningful) X.509 certificate DER blob for testing field extraction.
    """
    validity = _seq(_time(time_tag, not_before), _time(time_tag, not_after))
    sig_alg = _seq(_oid("1.2.840.113549.1.1.11"))
    tbs_children = [
        _int(1),  # serialNumber
        sig_alg,
        _seq(),  # issuer (empty RDNSequence, fine for our navigation)
        validity,
        _seq(),  # subject
        _seq(),  # subjectPublicKeyInfo
    ]
    if voms_ext_content is not None:
        extension = _seq(_oid(VOMS_EXTENSION_OID), _octet_string(voms_ext_content))
        tbs_children.append(_context(3, _seq(extension)))
    tbs_certificate = _seq(*tbs_children)
    return _seq(tbs_certificate, sig_alg, _tlv(0x03, b"\x00"))


def _pem(der_certs: list[bytes]) -> str:
    import base64

    blocks = []
    for der in der_certs:
        b64 = base64.b64encode(der).decode()
        lines = "\n".join(b64[i:i + 64] for i in range(0, len(b64), 64))
        blocks.append(f"-----BEGIN CERTIFICATE-----\n{lines}\n-----END CERTIFICATE-----")
    return "\n".join(blocks)


# ---- Tests ----


class TestPemCerts:
    def test_extracts_multiple(self):
        cert1 = _build_cert(datetime.now(timezone.utc), datetime.now(timezone.utc))
        cert2 = _build_cert(datetime.now(timezone.utc), datetime.now(timezone.utc))
        pem_text = _pem([cert1, cert2])
        certs = pem_certs(pem_text)
        assert len(certs) == 2
        assert certs[0] == cert1
        assert certs[1] == cert2

    def test_no_certificates(self):
        assert pem_certs("no certs here") == []


class TestX509Validity:
    def test_utctime(self):
        nb = datetime(2026, 8, 11, 11, 34, 4, tzinfo=timezone.utc)
        na = datetime(2026, 8, 11, 23, 34, 4, tzinfo=timezone.utc)
        cert = _build_cert(nb, na, time_tag=TAG_UTCTIME)
        assert x509_validity(cert) == (nb, na)

    def test_generalizedtime(self):
        nb = datetime(2026, 8, 11, 11, 34, 4, tzinfo=timezone.utc)
        na = datetime(2026, 8, 11, 23, 34, 4, tzinfo=timezone.utc)
        cert = _build_cert(nb, na, time_tag=TAG_GENERALIZEDTIME)
        assert x509_validity(cert) == (nb, na)

    def test_utctime_pivot_year(self):
        # Two-digit year 30 -> 2030 (< 50 pivot), 60 -> 1960 (>= 50 pivot)
        nb = datetime(2030, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        na = datetime(2030, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
        cert = _build_cert(nb, na, time_tag=TAG_UTCTIME)
        assert x509_validity(cert) == (nb, na)


class TestFindExtension:
    def test_present(self):
        content = b"some-voms-ac-bytes"
        cert = _build_cert(
            datetime.now(timezone.utc), datetime.now(timezone.utc), voms_ext_content=content
        )
        assert find_extension(cert, VOMS_EXTENSION_OID) == content

    def test_absent(self):
        cert = _build_cert(datetime.now(timezone.utc), datetime.now(timezone.utc))
        assert find_extension(cert, VOMS_EXTENSION_OID) is None

    def test_wrong_oid_not_matched(self):
        cert = _build_cert(
            datetime.now(timezone.utc),
            datetime.now(timezone.utc),
            voms_ext_content=b"irrelevant",
        )
        assert find_extension(cert, "1.2.3.4.5") is None


class TestVomsAcValidity:
    def test_simple_top_level(self):
        nb = datetime(2026, 8, 11, 11, 34, 4, tzinfo=timezone.utc)
        na = datetime(2026, 8, 11, 23, 34, 4, tzinfo=timezone.utc)
        ac = _seq(_time(TAG_GENERALIZEDTIME, nb), _time(TAG_GENERALIZEDTIME, na))
        assert voms_ac_validity(ac) == (nb, na)

    def test_nested_like_real_voms_ac(self):
        """Mirrors the real structure: acinfo containing holder/issuer/sigAlg/
        serial before attrCertValidityPeriod, and an attributes sequence
        (with unrelated OCTET STRING/OID content, e.g. FQANs) after it.
        """
        nb = datetime(2026, 8, 11, 11, 34, 4, tzinfo=timezone.utc)
        na = datetime(2026, 8, 11, 23, 34, 4, tzinfo=timezone.utc)

        holder = _seq(_octet_string(b"holder-placeholder"))
        issuer = _seq(_octet_string(b"issuer-placeholder"))
        sig_alg = _seq(_oid("1.2.840.113549.1.1.11"))
        serial = _int(42)
        validity_period = _seq(_time(TAG_GENERALIZEDTIME, nb), _time(TAG_GENERALIZEDTIME, na))
        fqan_attr = _seq(
            _oid("1.3.6.1.4.1.8005.100.100.4"),
            _octet_string(b"/saradmins/Role=dteam/Capability=NULL"),
        )
        attributes = _seq(fqan_attr)
        acinfo = _seq(holder, issuer, sig_alg, serial, validity_period, attributes)
        ac = _seq(acinfo, sig_alg, _tlv(0x03, b"\x00"))

        assert voms_ac_validity(ac) == (nb, na)

    def test_first_match_wins_over_later_decoy(self):
        """A validity-period-shaped SEQUENCE appearing later in the tree
        (e.g. inside attributes) must not override the real, earlier one.
        """
        real_nb = datetime(2026, 8, 11, 11, 34, 4, tzinfo=timezone.utc)
        real_na = datetime(2026, 8, 11, 23, 34, 4, tzinfo=timezone.utc)
        decoy_nb = datetime(2000, 1, 1, tzinfo=timezone.utc)
        decoy_na = datetime(2000, 1, 2, tzinfo=timezone.utc)

        real_validity = _seq(
            _time(TAG_GENERALIZEDTIME, real_nb), _time(TAG_GENERALIZEDTIME, real_na)
        )
        decoy = _seq(_time(TAG_GENERALIZEDTIME, decoy_nb), _time(TAG_GENERALIZEDTIME, decoy_na))
        acinfo = _seq(real_validity, _seq(decoy))
        ac = _seq(acinfo)

        assert voms_ac_validity(ac) == (real_nb, real_na)

    def test_malformed_returns_none(self):
        assert voms_ac_validity(b"\xff\xff not valid der") is None

    def test_no_validity_period_returns_none(self):
        ac = _seq(_octet_string(b"nothing time-shaped in here"))
        assert voms_ac_validity(ac) is None


class TestParseDerErrors:
    def test_truncated_length_raises(self):
        with pytest.raises(AdaAuthError):
            x509_validity(b"\x30\x05\x01\x02")  # SEQUENCE claims 5 bytes, has 2
