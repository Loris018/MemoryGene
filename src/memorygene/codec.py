"""dna-v1: UTF-8 bytes -> four bases per byte; no compression claim."""

import hashlib

BASES = "ACGT"


def encode(data: bytes) -> str:
    return "".join(BASES[(b >> shift) & 3] for b in data for shift in (6, 4, 2, 0))


def decode(bases: str) -> bytes:
    if len(bases) % 4 or any(c not in BASES for c in bases):
        raise ValueError("Invalid dna-v1 sequence")
    return bytes(
        sum(BASES.index(bases[i + j]) << (6 - 2 * j) for j in range(4))
        for i in range(0, len(bases), 4)
    )


def complement(bases: str) -> str:
    if any(c not in BASES for c in bases):
        raise ValueError("Invalid dna-v1 sequence")
    return bases.translate(str.maketrans("ACGT", "TGCA"))


def packed_complement(data: bytes) -> bytes:
    """Packing four complementary bases per byte is exactly XOR 0xff."""
    return bytes(b ^ 255 for b in data)


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class IntegrityError(ValueError):
    pass


def recover(
    primary: bytes, backup: bytes | None, expected: str, protection: str
) -> bytes:
    if protection not in {"none", "copy", "complement"}:
        raise ValueError("Unknown protection mode")
    if checksum(primary) == expected:
        return primary
    if backup is not None and protection != "none":
        candidate = packed_complement(backup) if protection == "complement" else backup
        if checksum(candidate) == expected:
            return candidate
    raise IntegrityError("No verified copy; refusing to guess")
