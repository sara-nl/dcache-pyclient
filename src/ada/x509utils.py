"""Minimal DER/ASN.1 helpers for X.509 proxy certificate validation.

Implements just enough of DER to answer two questions about a grid
proxy certificate, without depending on an external crypto library or
shelling out to ``voms-proxy-info``:

1. When does the X.509 certificate itself expire (``tbsCertificate.validity``)?
2. If it carries a VOMS attribute certificate (the non-critical extension
   with OID ``1.3.6.1.4.1.8005.100.100.5``), when do the VOMS attributes
   (FQANs/roles) expire? That is a *separate* validity window
   (``AttCertValidityPeriod`` per RFC 3281), often different from the
   certificate's own validity.

This is not a general-purpose ASN.1 library: it only decodes tag/length/
value structure generically, and locates the fields we need by shape
(e.g. "the SEQUENCE holding exactly two GeneralizedTime values") rather
than by fully modelling the X.509 or RFC 3281 schemas. VOMS attribute
certificates in particular use several CHOICE types (holder, issuer)
that are awkward to model fully but irrelevant to finding the validity
period.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ada.exceptions import AdaAuthError

VOMS_EXTENSION_OID = "1.3.6.1.4.1.8005.100.100.5"

_TAG_UTCTIME = 0x17
_TAG_GENERALIZEDTIME = 0x18
_TAG_OBJECT_IDENTIFIER = 0x06
_TAG_OCTET_STRING = 0x04
_TAG_SEQUENCE = 0x30


@dataclass
class DerNode:
    """A single decoded DER TLV element."""

    tag: int
    is_constructed: bool
    value: bytes
    children: list["DerNode"] = field(default_factory=list)


def parse_der(data: bytes) -> list[DerNode]:
    """Decode a sequence of DER TLV elements at the top level of ``data``.

    Constructed elements (SEQUENCE, SET, and context-specific constructed
    tags) are recursed into automatically; primitive elements keep their
    raw value bytes.
    """
    nodes: list[DerNode] = []
    offset = 0
    while offset < len(data):
        node, offset = _parse_one(data, offset)
        nodes.append(node)
    return nodes


def _parse_one(data: bytes, offset: int) -> tuple[DerNode, int]:
    if offset >= len(data):
        raise AdaAuthError("Invalid DER data: unexpected end of data")

    tag_byte = data[offset]
    is_constructed = bool(tag_byte & 0x20)
    # Only low-tag-number form (tag number <= 30) is expected in the
    # structures we parse here (X.509 certs and VOMS ACs don't use
    # multi-byte tag numbers for the fields we care about).
    offset += 1

    if offset >= len(data):
        raise AdaAuthError("Invalid DER data: truncated length")
    length_byte = data[offset]
    offset += 1
    if length_byte & 0x80:
        num_length_bytes = length_byte & 0x7F
        if num_length_bytes == 0:
            raise AdaAuthError("Invalid DER data: indefinite length not supported")
        if offset + num_length_bytes > len(data):
            raise AdaAuthError("Invalid DER data: truncated length bytes")
        length = int.from_bytes(data[offset:offset + num_length_bytes], "big")
        offset += num_length_bytes
    else:
        length = length_byte

    if offset + length > len(data):
        raise AdaAuthError("Invalid DER data: truncated value")
    value = data[offset:offset + length]
    offset += length

    node = DerNode(tag=tag_byte, is_constructed=is_constructed, value=value)
    if is_constructed:
        node.children = parse_der(value)
    return node, offset


def _decode_oid(value: bytes) -> str:
    if not value:
        return ""
    parts = []
    first = value[0]
    parts.append(str(first // 40))
    parts.append(str(first % 40))
    current = 0
    for byte in value[1:]:
        current = (current << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(str(current))
            current = 0
    return ".".join(parts)


def _decode_time(node: DerNode) -> datetime:
    text = node.value.decode("ascii")
    if node.tag == _TAG_UTCTIME:
        # YYMMDDHHMM[SS]Z -- two-digit year, pivot at 50 (RFC 5280 4.1.2.5.1)
        match = re.match(r"^(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})?Z$", text)
        if not match:
            raise AdaAuthError(f"Invalid UTCTime value: {text!r}")
        yy = int(match.group(1))
        year = 2000 + yy if yy < 50 else 1900 + yy
        month, day, hour, minute = (int(match.group(i)) for i in (2, 3, 4, 5))
        second = int(match.group(6)) if match.group(6) else 0
    elif node.tag == _TAG_GENERALIZEDTIME:
        # YYYYMMDDHHMM[SS]Z -- fractional seconds not expected/handled here.
        match = re.match(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})?Z$", text)
        if not match:
            raise AdaAuthError(f"Invalid GeneralizedTime value: {text!r}")
        year, month, day, hour, minute = (int(match.group(i)) for i in (1, 2, 3, 4, 5))
        second = int(match.group(6)) if match.group(6) else 0
    else:
        raise AdaAuthError(f"Unsupported time tag: 0x{node.tag:02x}")
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def pem_certs(pem_text: str) -> list[bytes]:
    """Extract DER-encoded certificates from PEM text.

    A proxy file typically contains one or more certificates followed by
    a private key (and possibly CA chain certificates); only the
    ``CERTIFICATE`` blocks are relevant here.
    """
    import base64

    blocks = re.findall(
        r"-----BEGIN CERTIFICATE-----(.*?)-----END CERTIFICATE-----",
        pem_text,
        re.S,
    )
    return [base64.b64decode("".join(block.split())) for block in blocks]


def x509_validity(der_cert: bytes) -> tuple[datetime, datetime]:
    """Return (notBefore, notAfter) for an X.509 certificate's own validity."""
    top = parse_der(der_cert)
    if not top or not top[0].children:
        raise AdaAuthError("Invalid X.509 certificate: cannot parse structure")
    tbs_certificate = top[0].children[0]

    for child in tbs_certificate.children:
        if child.tag == _TAG_SEQUENCE and len(child.children) == 2:
            first, second = child.children
            if first.tag in (_TAG_UTCTIME, _TAG_GENERALIZEDTIME) and second.tag in (
                _TAG_UTCTIME,
                _TAG_GENERALIZEDTIME,
            ):
                return _decode_time(first), _decode_time(second)

    raise AdaAuthError("Invalid X.509 certificate: validity period not found")


def find_extension(der_cert: bytes, oid: str) -> Optional[bytes]:
    """Return the raw OCTET STRING content of the extension with the given OID."""
    top = parse_der(der_cert)
    if not top or not top[0].children:
        return None
    tbs_certificate = top[0].children[0]

    # extensions field is a context-specific constructed tag ([3]) holding
    # a single SEQUENCE OF Extension; find it by walking constructed
    # context-specific children rather than assuming a fixed index, since
    # optional preceding fields (issuerUniqueID etc.) shift the position.
    for child in tbs_certificate.children:
        if not child.is_constructed or (child.tag & 0xC0) != 0x80:
            continue
        for maybe_seq in child.children:
            if maybe_seq.tag != _TAG_SEQUENCE:
                continue
            for extension in maybe_seq.children:
                if extension.tag != _TAG_SEQUENCE or not extension.children:
                    continue
                oid_node = extension.children[0]
                if oid_node.tag != _TAG_OBJECT_IDENTIFIER:
                    continue
                if _decode_oid(oid_node.value) != oid:
                    continue
                for part in extension.children[1:]:
                    if part.tag == _TAG_OCTET_STRING:
                        return part.value
    return None


def _find_validity_period(node: DerNode) -> Optional[tuple[datetime, datetime]]:
    """Depth-first search for a SEQUENCE of exactly two GeneralizedTime values.

    Used to locate an RFC 3281 ``AttCertValidityPeriod`` inside a VOMS
    attribute certificate without modelling the full (and partly CHOICE-
    based) AttributeCertificateInfo schema.
    """
    if node.tag == _TAG_SEQUENCE and len(node.children) == 2:
        first, second = node.children
        if first.tag == _TAG_GENERALIZEDTIME and second.tag == _TAG_GENERALIZEDTIME:
            return _decode_time(first), _decode_time(second)

    for child in node.children:
        found = _find_validity_period(child)
        if found:
            return found
    return None


def voms_ac_validity(ac_der: bytes) -> Optional[tuple[datetime, datetime]]:
    """Return (notBeforeTime, notAfterTime) for a VOMS attribute certificate.

    Returns None if the structure doesn't contain a recognizable
    validity period (e.g. an unexpected/future VOMS encoding) rather
    than raising, so callers can fall back to X.509-only validation.
    """
    try:
        top = parse_der(ac_der)
        for node in top:
            found = _find_validity_period(node)
            if found:
                return found
    except AdaAuthError:
        return None
    return None
