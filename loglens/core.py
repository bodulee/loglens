"""Parse Common/Combined access logs and aggregate streaming records."""

from collections import Counter
from dataclasses import dataclass
import re


QUOTED = r'"(?:[^"\\\r\n]|\\[^\r\n])*"'
LINE = re.compile(
    r'(?P<client>\S+)[ \t]+\S+[ \t]+\S+[ \t]+'
    r'\[\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4}\][ \t]+'
    rf'(?P<request>{QUOTED})[ \t]+'
    r'(?P<status>[1-5]\d{2})[ \t]+(?P<size>\d+|-)'
    rf'(?:[ \t]+{QUOTED}[ \t]+{QUOTED})?[ \t]*'
)


@dataclass(frozen=True)
class Entry:
    client: str
    method: str
    target: str
    status: int
    size: int | None


def parse_line(line: str) -> Entry | None:
    """Return None for unsupported lines; preserve log-escaped field content."""
    match = LINE.fullmatch(line.rstrip("\r\n"))
    if match is None:
        return None
    request = match["request"][1:-1]
    if request == "-":
        method, target = "-", "-"
    else:
        parts = request.split()
        if len(parts) != 3 or not re.fullmatch(r"HTTP/\d+(?:\.\d+)?", parts[2]):
            return None
        method, target = parts[:2]
    try:
        size = None if match["size"] == "-" else int(match["size"])
    except ValueError:
        return None
    return Entry(match["client"], method, target, int(match["status"]), size)


class Summary:
    """Keep counters rather than complete log records."""

    def __init__(self, keep_query: bool = False):
        self.keep_query = keep_query
        self.lines_read = 0
        self.blank_lines = 0
        self.malformed_lines = 0
        self.requests = 0
        self.bytes_sent = 0
        self.unknown_size_requests = 0
        self.errors = 0
        self.status_codes: Counter[str] = Counter()
        self.methods: Counter[str] = Counter()
        self.clients: Counter[str] = Counter()
        self.paths: Counter[str] = Counter()

    def add(self, line: str) -> None:
        self.lines_read += 1
        if not line.strip():
            self.blank_lines += 1
            return
        entry = parse_line(line)
        if entry is None:
            self.malformed_lines += 1
            return
        self.requests += 1
        self.errors += entry.status >= 400
        self.bytes_sent += entry.size or 0
        self.unknown_size_requests += entry.size is None
        self.status_codes[str(entry.status)] += 1
        self.methods[entry.method] += 1
        self.clients[entry.client] += 1
        path = entry.target if self.keep_query else entry.target.partition("?")[0]
        self.paths[path] += 1

    def report(self, top: int = 10) -> dict:
        def ranked(counter: Counter[str]) -> list[dict]:
            return [
                {"value": value, "count": count}
                for value, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:top]
            ]

        return {
            "lines_read": self.lines_read,
            "requests": self.requests,
            "blank_lines": self.blank_lines,
            "malformed_lines": self.malformed_lines,
            "bytes_sent": self.bytes_sent,
            "unknown_size_requests": self.unknown_size_requests,
            "errors": self.errors,
            "error_rate_percent": round(100 * self.errors / self.requests, 2) if self.requests else 0.0,
            "unique_clients": len(self.clients),
            "status_codes": dict(sorted(self.status_codes.items())),
            "methods": dict(sorted(self.methods.items())),
            "top_clients": ranked(self.clients),
            "top_paths": ranked(self.paths),
        }
