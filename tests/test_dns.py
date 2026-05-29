"""Tests for ecfs.core.dns — DNS tunneling helpers."""

import pytest

from ecfs.core.dns import (
    encode_to_dns_label,
    decode_from_dns_label,
    generate_subdomain,
    extract_data_from_subdomain,
)


def test_encode_decode_roundtrip():
    """Encoded data can be decoded back to original."""
    original = b"Hello, ECFS!"
    labels = encode_to_dns_label(original)
    decoded = decode_from_dns_label(labels)
    assert decoded == original


def test_encode_to_dns_label():
    """Data is encoded into valid DNS labels."""
    data = b"test payload"
    labels = encode_to_dns_label(data)
    assert len(labels) > 0
    # All labels should be <= 63 chars
    for label in labels:
        assert len(label) <= 63
    # Labels should only contain alphanumeric chars (base32: a-z, 2-7)
    for label in labels:
        assert all(c in 'abcdefghijklmnopqrstuvwxyz234567' for c in label)


def test_decode_from_dns_label():
    """DNS labels decode back to original bytes."""
    original = b"test data"
    labels = encode_to_dns_label(original)
    decoded = decode_from_dns_label(labels)
    assert decoded == original


def test_generate_subdomain_format():
    """Generated subdomain has correct format: <hash>.<data_labels>.<domain>."""
    data = b"secret data"
    subdomain = generate_subdomain(data, "example.com")
    parts = subdomain.split('.')
    # Last part should be 'com' (end of domain)
    assert parts[-1] == "com"
    assert parts[-2] == "example"
    # First part should be 8-char hex hash
    assert len(parts[0]) == 8
    assert all(c in '0123456789abcdef' for c in parts[0])
    # There should be at least 3 parts: hash, data, domain components
    assert len(parts) >= 3


def test_extract_data_from_subdomain():
    """Data can be extracted from a generated subdomain."""
    original = b"steganographic data"
    subdomain = generate_subdomain(original, "example.com")
    extracted = extract_data_from_subdomain(subdomain, "example.com")
    assert extracted == original


def test_empty_data():
    """Encoding/decoding empty data works without errors."""
    labels = encode_to_dns_label(b"")
    assert labels == []
    decoded = decode_from_dns_label(labels)
    assert decoded == b''


def test_large_data():
    """Encoding/decoding large data works with multiple labels."""
    original = b"x" * 200  # Will need multiple DNS labels
    labels = encode_to_dns_label(original)
    assert len(labels) > 1  # Should produce multiple labels
    for label in labels:
        assert len(label) <= 63
    decoded = decode_from_dns_label(labels)
    assert decoded == original


def test_generate_extract_roundtrip_various_domains():
    """Roundtrip works with various domain formats."""
    original = b"test data 123"
    for domain in ["com", "example.com", "sub.example.co.uk"]:
        subdomain = generate_subdomain(original, domain)
        extracted = extract_data_from_subdomain(subdomain, domain)
        assert extracted == original, f"Failed for domain: {domain}"
