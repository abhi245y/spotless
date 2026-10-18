#!/usr/bin/env python3
"""Validate/rebuild captured WebKit format-16 inline cache records offline.

Sources: WebKit main Source/WTF/wtf/persistence/PersistentEncoder.{h,cpp},
PersistentCoders.cpp and Source/WebKit/NetworkProcess/cache/
NetworkCache{Coders,Data,Storage}.cpp. Metadata checksum uses typed SHA1;
record header/body hashes use SHA1(cache_salt || bytes). No network or console
operations. HTTP/certificate header bytes remain opaque and unchanged.
"""

import argparse
from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import struct

MAX_RECORD_BYTES = 32 * 1024 * 1024
MAX_STRING_CHARS = 1024 * 1024


class RecordError(ValueError):
    """Unsupported or corrupt cache record; no output should be installed."""


class TypedDecoder:
    """Little-endian Sony x86-64 persistence values with WebKit type tags."""

    def __init__(self, data):
        self.data = data
        self.position = 0
        self.checksum = hashlib.sha1()

    def take(self, count, tag):
        if count < 0 or count > len(self.data) - self.position:
            raise RecordError("truncated persistence value")
        value = self.data[self.position:self.position + count]
        self.position += count
        self.checksum.update(struct.pack("<I", tag))
        self.checksum.update(value)
        return value

    def number(self, fmt, tag):
        return struct.unpack("<" + fmt, self.take(struct.calcsize("<" + fmt), tag))[0]

    def boolean(self):
        value = self.number("B", 3)
        if value not in (0, 1):
            raise RecordError("invalid encoded boolean")
        return bool(value)

    def string(self):
        length = self.number("I", 11)
        if length == 0xffffffff:
            return None
        if length > MAX_STRING_CHARS:
            raise RecordError("oversized encoded string")
        is_8bit = self.boolean()
        raw = self.take(length * (1 if is_8bit else 2), 101)
        try:
            return raw.decode("latin1" if is_8bit else "utf-16-le")
        except UnicodeDecodeError as error:
            raise RecordError("invalid UTF-16 string") from error


@dataclass(frozen=True)
class Metadata:
    version: int
    partition: str | None
    resource_type: str | None
    identifier: str | None
    byte_range: str | None
    key_hash: bytes
    partition_hash: bytes
    timestamp: float
    header_hash: bytes
    header_size: int
    body_hash: bytes
    body_size: int
    inline: bool
    header_hash_offset: int
    body_hash_offset: int
    body_size_offset: int
    checksum_offset: int
    checksum: bytes
    header_offset: int

    @property
    def body_offset(self):
        return self.header_offset + self.header_size


def decode_metadata(record, *, verify=True):
    """Decode exactly format-16 metadata; offsets come from parsed fields."""
    if len(record) > MAX_RECORD_BYTES:
        raise RecordError("record exceeds analysis size limit")
    decoder = TypedDecoder(record)
    version = decoder.number("I", 11)
    if version != 16:
        raise RecordError("only captured format 16 is supported")
    partition, resource_type, identifier, byte_range = [decoder.string() for _ in range(4)]
    key_hash = decoder.take(20, 101)
    partition_hash = decoder.take(20, 101)
    timestamp = decoder.number("d", 29)
    if not math.isfinite(timestamp):
        raise RecordError("invalid record timestamp")
    header_hash_offset = decoder.position
    header_hash = decoder.take(20, 101)
    header_size = decoder.number("Q", 13)
    body_hash_offset = decoder.position
    body_hash = decoder.take(20, 101)
    body_size_offset = decoder.position
    body_size = decoder.number("Q", 13)
    inline = decoder.boolean()
    checksum_offset = decoder.position
    calculated = decoder.checksum.digest()
    checksum = decoder.take(20, 101)
    if verify and not hmac.compare_digest(checksum, calculated):
        raise RecordError("metadata typed checksum mismatch")
    return Metadata(version, partition, resource_type, identifier, byte_range,
                    key_hash, partition_hash, timestamp, header_hash, header_size,
                    body_hash, body_size, inline, header_hash_offset,
                    body_hash_offset, body_size_offset, checksum_offset,
                    calculated, decoder.position)


def salted_sha1(data, salt):
    if not isinstance(salt, bytes) or not salt or len(salt) > 4096:
        raise RecordError("cache salt must be nonempty bounded bytes")
    return hashlib.sha1(salt + data).digest()


def validate_record(record, salt):
    metadata = decode_metadata(record)
    if not metadata.inline:
        raise RecordError("external blob bodies are unsupported")
    if metadata.body_offset > len(record):
        raise RecordError("header size exceeds record")
    if metadata.body_offset + metadata.body_size != len(record):
        raise RecordError("inline body size does not match record length")
    header = record[metadata.header_offset:metadata.body_offset]
    body = record[metadata.body_offset:]
    if not hmac.compare_digest(metadata.header_hash, salted_sha1(header, salt)):
        raise RecordError("salted header checksum mismatch")
    if not hmac.compare_digest(metadata.body_hash, salted_sha1(body, salt)):
        raise RecordError("salted body checksum mismatch")
    return metadata


def rebuild_record(record, replacement_body, salt):
    """Validate original first; change only body, body hash/size, checksum."""
    metadata = validate_record(record, salt)
    if not isinstance(replacement_body, bytes):
        raise RecordError("replacement body must be bytes")
    if metadata.body_offset + len(replacement_body) > MAX_RECORD_BYTES:
        raise RecordError("replacement record exceeds analysis size limit")
    result = bytearray(record[:metadata.body_offset])
    result[metadata.body_hash_offset:metadata.body_hash_offset + 20] = salted_sha1(replacement_body, salt)
    struct.pack_into("<Q", result, metadata.body_size_offset, len(replacement_body))
    new_checksum = decode_metadata(result, verify=False).checksum
    result[metadata.checksum_offset:metadata.checksum_offset + 20] = new_checksum
    result.extend(replacement_body)
    result = bytes(result)
    updated = validate_record(result, salt)
    if result[updated.header_offset:updated.body_offset] != record[metadata.header_offset:metadata.body_offset]:
        raise RecordError("unexpected header mutation")
    return result


def summarize(record, metadata):
    return {"version": metadata.version, "resource_type": metadata.resource_type,
            "identifier": metadata.identifier, "bytes": len(record),
            "sha256": hashlib.sha256(record).hexdigest(),
            "metadata_checksum": metadata.checksum.hex(),
            "header_offset": metadata.header_offset, "header_size": metadata.header_size,
            "header_sha256": hashlib.sha256(record[metadata.header_offset:metadata.body_offset]).hexdigest(),
            "body_offset": metadata.body_offset, "body_size": metadata.body_size,
            "body_sha256": hashlib.sha256(record[metadata.body_offset:]).hexdigest(),
            "typed_metadata_and_salted_header_body_valid": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--salt", required=True, type=Path)
    parser.add_argument("--body", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if (args.body is None) != (args.output is None):
        parser.error("--body and --output must be used together")
    original = args.record.read_bytes()
    salt = args.salt.read_bytes()
    metadata = validate_record(original, salt)
    report = {"original": summarize(original, metadata),
              "runtime_acceptance": "not tested; offline record integrity only"}
    if args.body is not None:
        if args.output.resolve() in {args.record.resolve(), args.body.resolve(), args.salt.resolve()}:
            parser.error("output must not replace an input")
        result = rebuild_record(original, args.body.read_bytes(), salt)
        # Exclusive creation prevents any original or prior result overwrite.
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(result)
        report["rebuilt"] = summarize(result, validate_record(result, salt))
        report["header_preserved_byte_for_byte"] = True
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
