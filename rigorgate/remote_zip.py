from __future__ import annotations

import binascii
import json
import re
import struct
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .http import ProviderError


RangeReader = Callable[[int, int], tuple[bytes, int]]


@dataclass(frozen=True)
class ZipMember:
    name: str
    compression: int
    crc32: int
    compressed_size: int
    uncompressed_size: int
    local_header_offset: int


class HttpRangeReader:
    """Read small byte ranges without downloading a multi-gigabyte SEC archive."""

    def __init__(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout_seconds: int = 45,
        min_interval_seconds: float = 0.12,
    ) -> None:
        self.url = url
        self.headers = dict(headers or {})
        self.timeout_seconds = timeout_seconds
        self.min_interval_seconds = min_interval_seconds
        self._last_call = 0.0

    def __call__(self, start: int, end: int) -> tuple[bytes, int]:
        if start < 0 or end < start:
            raise ProviderError("invalid HTTP byte range")
        elapsed = time.monotonic() - self._last_call
        if self._last_call and elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)
        request = urllib.request.Request(
            self.url,
            headers={
                "Accept": "application/zip, application/octet-stream",
                "Accept-Encoding": "identity",
                "Range": f"bytes={start}-{end}",
                "User-Agent": "RigorGate-Alpha-Scanner/0.2",
                **self.headers,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                self._last_call = time.monotonic()
                status = getattr(response, "status", response.getcode())
                content_range = response.headers.get("Content-Range", "")
                match = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+)", content_range.strip())
                if status != 206 or not match:
                    raise ProviderError(
                        "SEC bulk archive did not honor a safe byte-range request"
                    )
                payload = response.read()
                expected = int(match.group(2)) - int(match.group(1)) + 1
                if len(payload) != expected:
                    raise ProviderError("SEC bulk archive returned a truncated byte range")
                return payload, int(match.group(3))
        except urllib.error.HTTPError as exc:
            self._last_call = time.monotonic()
            raise ProviderError(f"HTTP {exc.code} from SEC bulk archive") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            self._last_call = time.monotonic()
            raise ProviderError(f"SEC bulk archive request failed: {exc}") from exc


class RemoteZipJsonArchive:
    """Read selected JSON members from a remote ZIP using its central directory."""

    EOCD_SIGNATURE = b"PK\x05\x06"
    CENTRAL_SIGNATURE = b"PK\x01\x02"
    LOCAL_SIGNATURE = b"PK\x03\x04"

    def __init__(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        range_reader: RangeReader | None = None,
        max_directory_bytes: int = 64 * 1024 * 1024,
        max_member_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        self.url = url
        self.reader = range_reader or HttpRangeReader(url, headers=headers)
        self.max_directory_bytes = max_directory_bytes
        self.max_member_bytes = max_member_bytes
        self._total_size: int | None = None
        self._members: dict[str, ZipMember] | None = None

    def _size(self) -> int:
        if self._total_size is None:
            _, self._total_size = self.reader(0, 0)
        return self._total_size

    def _load_directory(self) -> dict[str, ZipMember]:
        if self._members is not None:
            return self._members
        total = self._size()
        tail_start = max(0, total - 65_557)
        tail, confirmed_total = self.reader(tail_start, total - 1)
        if confirmed_total != total:
            raise ProviderError("SEC bulk archive size changed during retrieval")
        eocd_at = tail.rfind(self.EOCD_SIGNATURE)
        if eocd_at < 0 or len(tail) - eocd_at < 22:
            raise ProviderError("SEC bulk archive end record was not found")
        fields = struct.unpack_from("<4s4H2LH", tail, eocd_at)
        entries_total, directory_size, directory_offset = fields[4], fields[5], fields[6]
        if directory_size == 0xFFFFFFFF or directory_offset == 0xFFFFFFFF:
            raise ProviderError("SEC bulk archive unexpectedly requires ZIP64 directory support")
        if directory_size > self.max_directory_bytes:
            raise ProviderError("SEC bulk archive directory exceeded the safety limit")
        if directory_offset + directory_size > total:
            raise ProviderError("SEC bulk archive directory points outside the file")
        directory, _ = self.reader(
            directory_offset, directory_offset + directory_size - 1
        )
        members: dict[str, ZipMember] = {}
        offset = 0
        parsed = 0
        while offset < len(directory):
            if directory[offset : offset + 4] != self.CENTRAL_SIGNATURE:
                raise ProviderError("SEC bulk archive central directory is malformed")
            if len(directory) - offset < 46:
                raise ProviderError("SEC bulk archive central entry is truncated")
            values = struct.unpack_from("<4s6H3L5H2L", directory, offset)
            compression = values[4]
            crc32 = values[7]
            compressed_size = values[8]
            uncompressed_size = values[9]
            name_length, extra_length, comment_length = values[10], values[11], values[12]
            local_offset = values[16]
            if 0xFFFFFFFF in {compressed_size, uncompressed_size, local_offset}:
                raise ProviderError("SEC bulk archive member unexpectedly requires ZIP64 support")
            start = offset + 46
            stop = start + name_length
            name = directory[start:stop].decode("utf-8")
            members[name] = ZipMember(
                name=name,
                compression=compression,
                crc32=crc32,
                compressed_size=compressed_size,
                uncompressed_size=uncompressed_size,
                local_header_offset=local_offset,
            )
            offset = stop + extra_length + comment_length
            parsed += 1
        if parsed != entries_total:
            raise ProviderError(
                f"SEC bulk archive directory count mismatch: {parsed} != {entries_total}"
            )
        self._members = members
        return members

    def _resolve_member(self, name: str) -> ZipMember:
        members = self._load_directory()
        if name in members:
            return members[name]
        suffix = f"/{name}"
        matches = [member for path, member in members.items() if path.endswith(suffix)]
        if len(matches) == 1:
            return matches[0]
        raise ProviderError(f"SEC bulk archive does not contain {name}")

    def read(self, name: str) -> bytes:
        member = self._resolve_member(name)
        if member.uncompressed_size > self.max_member_bytes:
            raise ProviderError(f"SEC bulk member {name} exceeded the safety limit")
        header, _ = self.reader(
            member.local_header_offset, member.local_header_offset + 29
        )
        if len(header) != 30 or header[:4] != self.LOCAL_SIGNATURE:
            raise ProviderError(f"SEC bulk member {name} has an invalid local header")
        values = struct.unpack("<4s5H3L2H", header)
        name_length, extra_length = values[9], values[10]
        data_start = member.local_header_offset + 30 + name_length + extra_length
        if member.compressed_size == 0:
            compressed = b""
        else:
            compressed, _ = self.reader(
                data_start, data_start + member.compressed_size - 1
            )
        try:
            if member.compression == 0:
                payload = compressed
            elif member.compression == 8:
                payload = zlib.decompress(compressed, -zlib.MAX_WBITS)
            else:
                raise ProviderError(
                    f"SEC bulk member {name} uses unsupported ZIP compression {member.compression}"
                )
        except zlib.error as exc:
            raise ProviderError(f"SEC bulk member {name} could not be decompressed") from exc
        if len(payload) != member.uncompressed_size:
            raise ProviderError(f"SEC bulk member {name} has an invalid uncompressed size")
        if (binascii.crc32(payload) & 0xFFFFFFFF) != member.crc32:
            raise ProviderError(f"SEC bulk member {name} failed CRC validation")
        return payload

    def read_json(self, name: str) -> dict[str, Any]:
        try:
            payload = json.loads(self.read(name).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError(f"SEC bulk member {name} is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderError(f"SEC bulk member {name} did not contain a JSON object")
        return payload
