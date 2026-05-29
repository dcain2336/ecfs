"""DNS resolution helper for DNS tunneling / steganography."""

import hashlib
import base64


def encode_to_dns_label(data: bytes, max_label: int = 63) -> list[str]:
    """Encode binary data as DNS-compatible labels.
    
    Uses base32 encoding. Labels are purely alphanumeric (a-z, 2-7)
    which are valid DNS label characters.
    """
    if not data:
        return []
    encoded = base64.b32encode(data).decode().lower().rstrip('=')
    labels = []
    for i in range(0, len(encoded), max_label):
        chunk = encoded[i:i + max_label]
        labels.append(chunk)
    return labels


def decode_from_dns_label(labels: list[str]) -> bytes:
    """Decode DNS labels back to binary data."""
    if not labels:
        return b''
    joined = ''.join(labels)
    # Pad base32
    padding = (8 - len(joined) % 8) % 8
    joined += '=' * padding
    return base64.b32decode(joined.upper())


def generate_subdomain(data: bytes, domain: str) -> str:
    """Generate a full subdomain for DNS steganography.
    
    Format: <hash_prefix>.<data_labels>.<domain>
    Hash prefix is always 8 hex characters and comes first.
    """
    labels = encode_to_dns_label(data)
    prefix = hashlib.sha256(data).hexdigest()[:8]
    data_part = '.'.join(labels) if labels else '_'
    return prefix + '.' + data_part + '.' + domain


def extract_data_from_subdomain(subdomain: str, domain: str) -> bytes:
    """Extract data from a steganographic subdomain.
    
    Args:
        subdomain: The full subdomain (e.g. "hash.labels.example.com")
        domain: The base domain to strip (e.g. "example.com")
    
    Format: <hash_prefix>.<data_labels>.<domain>
    Strips the domain suffix, then the hash prefix, and decodes the
    remaining data labels.
    """
    # Strip domain suffix
    if subdomain.endswith('.' + domain):
        prefix_and_data = subdomain[:-len(domain) - 1]
    else:
        prefix_and_data = subdomain
    
    parts = prefix_and_data.split('.')
    # parts[0] is hash prefix, remaining are data labels
    data_labels = parts[1:]
    return decode_from_dns_label(data_labels)
