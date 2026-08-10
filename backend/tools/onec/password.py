"""
Проверка пароля 1С по полю v8users.Data.

Алгоритм (как в PasswordChanger1C):
1) первый байт Data = длина ключа N
2) байты [1..N] = ключ
3) остальное XOR с циклическим ключом -> UTF-8 структура
4) в структуре — два SHA-1(Base64): пароль и пароль UPPER
5) SHA-1 считается от UTF-8 строки пароля
"""

from __future__ import annotations

import base64
import hashlib
import re


def decode_password_structure(data: bytes) -> tuple[str, int, bytes]:
    if not data:
        raise ValueError("Empty Data blob")

    key_size = data[0]
    if key_size <= 0 or key_size + 1 > len(data):
        raise ValueError(f"Invalid key size: {key_size}")

    key = data[1 : key_size + 1]
    payload = data[key_size + 1 :]

    decoded = bytearray(len(payload))
    j = 0
    for i, byte in enumerate(payload):
        decoded[i] = byte ^ key[j]
        j += 1
        if j >= key_size:
            j = 0

    text = decoded.decode("utf-8", errors="replace")
    return text, key_size, bytes(key)


def encrypt_string_sha1(password: str) -> str:
    digest = hashlib.sha1(password.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def extract_quoted_strings(structure: str) -> list[str]:
    return re.findall(r'"([^"]*)"', structure)


def extract_pass_hashes(structure: str) -> tuple[str, str]:
    """
    Heuristic: find pair of base64 SHA-1 hashes (28 chars ending with =).
    Falls back to parsing quoted strings around auth flags.
    """
    quoted = extract_quoted_strings(structure)
    b64_sha1 = [
        q for q in quoted if re.fullmatch(r"[A-Za-z0-9+/]{27}=", q) or re.fullmatch(r"[A-Za-z0-9+/]{28}", q)
    ]

    if len(b64_sha1) >= 2:
        return b64_sha1[0], b64_sha1[1]
    if len(b64_sha1) == 1:
        return b64_sha1[0], ""

    raw = re.findall(r"[A-Za-z0-9+/]{27}=", structure)
    if len(raw) >= 2:
        return raw[0], raw[1]
    if len(raw) == 1:
        return raw[0], ""

    return "", ""


def verify_password_details(data: bytes, password: str) -> dict:
    structure, key_size, key = decode_password_structure(data)
    hash1, hash2 = extract_pass_hashes(structure)

    expected = encrypt_string_sha1(password)
    expected_upper = encrypt_string_sha1(password.upper())

    match_plain = bool(hash1) and expected in {hash1, hash2}
    match_upper = bool(hash2 or hash1) and expected_upper in {hash1, hash2}

    return {
        "key_size": key_size,
        "structure_preview": structure[:300].replace("\n", " "),
        "structure_len": len(structure),
        "pass_hash": hash1,
        "pass_hash_upper": hash2,
        "expected": expected,
        "expected_upper": expected_upper,
        "match": match_plain or match_upper,
        "match_plain": match_plain,
        "match_upper": match_upper,
        "auth_disabled": '"0"' in structure[:200] and hash1 == "",
        "key": key,
    }


def verify_password(data: bytes, password: str) -> bool:
    """Return True if password matches hashes stored in 1C Data blob."""
    return bool(verify_password_details(data, password)["match"])
