"""
Network telemetry collector for Ingress.

This collector ingests and normalizes network-derived signals (local connection
snapshots, imported flow records, DNS/TLS metadata, pcap-derived artifacts,
etc.) into regular Ingress artifacts with full provenance.

**Scope and responsibility:**
- Ingress is an *analysis and fusion platform*. It can consume rich metadata
  produced by external authorized collection tools.
- The Ingress codebase itself does **not** implement packet capture, live
  traffic interception, remote network probing, or credential access.
- Any packet capture, flow collection, or deeper inspection must be performed
  by the operator (or their authorized systems) using separate tools, and only
  on networks/systems they have the legal right to monitor.
- Ingress will strip obvious raw payload or credential material if it is
  accidentally present in input records.

Operators are responsible for ensuring that all data they feed into Ingress
was collected in compliance with applicable law and authorization. See the
"Legal And Ethical Use" section in the project README for non-liability terms.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..models import Artifact, ProvenanceEntry, Source, SourceType

COUNTRY_CODE_TARGETS = {"IR": "iran", "RU": "russia", "CN": "china"}

TARGET_DOMAIN_SUFFIXES: dict[str, tuple[str, ...]] = {
    "iran": (
        # Core official military / MOD
        "mil.ir",
        "mod.ir",
        "army.ir",
        "navy.ir",
        "airforce.ir",
        "irgc.ir",
        "sepah.ir",
        "sepahnews.ir",
        # State media with heavy military coverage
        "tasnimnews.com",
        "mehrnews.com",
        "irna.ir",
        "farsnews.ir",
        "presstv.ir",
        "mashreghnews.ir",
        "javanonline.ir",
        "defapress.ir",
        "iranwatch.org",
        # Additional known defense/research related
        "defence.ir",
        # Broad .ir TLD as last-resort signal for Iranian infrastructure
        "ir",
    ),
    "russia": (
        # Core MOD / military
        "mil.ru",
        "structure.mil.ru",
        "eng.mil.ru",
        "mod.gov.ru",
        "vks.mil.ru",
        "navy.mil.ru",
        "mil.by",  # allied
        # State media & official channels with heavy mil content
        "tass.ru",
        "ria.ru",
        "interfax.ru",
        "kremlin.ru",
        "sputniknews.com",
        "zvezdanews.ru",
        "rg.ru",
        "iz.ru",
        "tvzvezda.ru",
        "redstar.ru",
        # Broad TLDs
        "ru",
        "su",
    ),
    "china": (
        # Core PLA / MOD
        "chinamil.com.cn",
        "81.cn",
        "mod.gov.cn",
        "pla.mil.cn",
        "navy.81.cn",
        "airforce.81.cn",
        "army.81.cn",
        "rocketforce.mil.cn",
        "space.81.cn",
        # State / defense media
        "globaltimes.cn",
        "news.cn",
        "xinhuanet.com",
        "people.cn",
        "scmp.com",  # frequently carries detailed PLA coverage
        "china-defense.blogspot.com",
        "81.cn",
        "cctv.com",  # state media often covers military
        # Broad TLD
        "cn",
    ),
}

RECORD_REMOTE_FIELDS = (
    "remote_domain",
    "domain",
    "server_name",
    "sni",
    "tls_sni",
    "query",
    "dns_query",
    "url",
    "remote_host",
    "dst_host",
    "destination_host",
    "remote",
    "destination",
    "dst",
)

# Fields commonly present in flow/packet-derived telemetry (authorized sources only).
# These are promoted into artifact metadata for OSINT value (endpoint attribution,
# fingerprinting, volume hints) without ever ingesting raw content.
RECORD_ENRICH_FIELDS = (
    "sni",
    "tls_sni",
    "server_name",
    "http_host",
    "host",
    "ja3",
    "ja3s",
    "hassh",
    "hassh_server",
    "bytes",
    "bytes_sent",
    "bytes_received",
    "orig_bytes",
    "resp_bytes",
    "duration",
    "duration_ms",
    "ts",
    "uid",
    "orig_h",
    "resp_h",
    "orig_p",
    "resp_p",
    "proto",
    "service",
    "dns_query",
    "dns_rcode",
    "query",
    "qtype_name",
    "http_method",
    "user_agent",
    "referer",
    "tls_version",
    "tls_cipher",
    "tls_subject",
    "tls_issuer",
    "event_type",
    "action",
    "src_asn",
    "dst_asn",
    "geoip",
)

# Keys that indicate raw or sensitive content. If present with non-trivial
# values we strip them (never store) and record a diagnostic. This is a safety
# measure for operators who might accidentally pipe richer pcaps/logs.
SENSITIVE_CONTENT_KEYS = (
    "payload",
    "payload_data",
    "data",
    "body",
    "content",
    "raw",
    "packet",
    "pcap",
    "full_packet",
    "http_body",
    "request_body",
    "response_body",
    "password",
    "passwd",
    "credential",
    "creds",
    "cookie",
    "authorization",
    "auth",
    "token",
    "secret",
    "keylog",
    "tls_key",
    "master_secret",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), timezone.utc)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.isdigit():
            return datetime.fromtimestamp(float(text), timezone.utc)
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            pass
    return _utc_now()


def _coerce_port(value: Any) -> int | None:
    if isinstance(value, int):
        return value if 0 <= value <= 65535 else None
    if isinstance(value, str) and value.isdigit():
        port = int(value)
        return port if 0 <= port <= 65535 else None
    return None


def split_endpoint(value: Any) -> tuple[str | None, int | None]:
    """Return host and optional port from URLs, host:port, IPv4, or bracketed IPv6."""
    if not value:
        return None, None
    text = str(value).strip()
    if not text:
        return None, None

    if "://" in text:
        parsed = urlparse(text)
        return parsed.hostname.lower() if parsed.hostname else None, _coerce_port(parsed.port)

    text = text.strip("<>")
    if "@" in text:
        text = text.rsplit("@", 1)[1]
    text = text.split("/", 1)[0].strip()

    if text.startswith("["):
        end = text.find("]")
        if end > 0:
            host = text[1:end]
            rest = text[end + 1 :]
            port = _coerce_port(rest[1:]) if rest.startswith(":") else None
            return host.lower(), port

    if text.count(":") == 1:
        host, possible_port = text.rsplit(":", 1)
        port = _coerce_port(possible_port)
        if port is not None:
            return host.lower().rstrip("."), port

    return text.lower().rstrip("."), None


def normalize_domain(value: Any) -> str | None:
    host, _ = split_endpoint(value)
    if not host:
        return None
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    if host == "localhost" or host.endswith(".local"):
        return None
    return host


def is_public_host(host: str | None) -> bool:
    if not host:
        return False
    clean = host.strip("[]").lower()
    if clean == "localhost" or clean.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(clean)
    except ValueError:
        return "." in clean
    return ip.is_global


def _domain_matches_suffix(domain: str, suffix: str) -> bool:
    clean_suffix = suffix.lower().lstrip(".")
    return domain == clean_suffix or domain.endswith("." + clean_suffix)


def _first_present(record: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _sanitize_record(record: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Return a copy with sensitive/raw content keys removed + list of warnings.

    This protects against accidental ingestion of actual packet payloads,
    credentials, or full content even if an operator exports richer logs.
    Only metadata (hosts, domains, sizes, fingerprints, high-level events)
    is retained for OSINT endpoint correlation.
    """
    cleaned: dict[str, Any] = {}
    warnings: list[str] = []
    for k, v in record.items():
        kl = k.lower()
        if kl in SENSITIVE_CONTENT_KEYS:
            if v not in (None, "", [], {}, False):
                warnings.append(f"sensitive key stripped: {k}")
            # do not copy the value
            continue
        cleaned[k] = v
    return cleaned, warnings


def _target_from_country_code(value: Any) -> str | None:
    if not value:
        return None
    return COUNTRY_CODE_TARGETS.get(str(value).strip().upper())


def infer_network_targets(record: dict[str, Any], domain: str | None, host: str | None) -> tuple[list[str], list[str]]:
    targets: set[str] = set()
    indicators: list[str] = []

    for key in ("target", "target_country"):
        value = record.get(key)
        if isinstance(value, str) and value:
            targets.add(value.lower())
            indicators.append(f"{key}:{value.lower()}")
    values = record.get("target_countries")
    if isinstance(values, list):
        for value in values:
            if isinstance(value, str) and value:
                targets.add(value.lower())
                indicators.append(f"target_countries:{value.lower()}")

    for key in ("country_code", "geoip_country", "dst_country", "remote_country"):
        target = _target_from_country_code(record.get(key))
        if target:
            targets.add(target)
            indicators.append(f"{key}:{record.get(key)}")

    if domain:
        for target, suffixes in TARGET_DOMAIN_SUFFIXES.items():
            for suffix in suffixes:
                if _domain_matches_suffix(domain, suffix):
                    targets.add(target)
                    indicators.append(f"domain_suffix:{suffix}")
                    break

    if host and not domain:
        target = _target_from_country_code(record.get("country_code"))
        if target:
            targets.add(target)

    ordered = [target for target in ("iran", "russia", "china") if target in targets]
    return ordered, indicators


def _record_timestamp(record: dict[str, Any]) -> datetime:
    return _parse_timestamp(record.get("timestamp") or record.get("ts") or record.get("time"))


def _record_process(record: dict[str, Any]) -> str | None:
    value = record.get("process") or record.get("process_name") or record.get("command")
    return str(value) if value not in (None, "") else None


class NetworkTelemetryCollector:
    """
    Convert local or imported network telemetry into Ingress artifacts.

    Records can be JSON objects with fields such as remote_domain, remote_host,
    remote_port, protocol, process, pid, state, country_code, and target_country.
    """

    def __init__(
        self,
        *,
        targets: list[str] | None = None,
        include_unfocused: bool = False,
        source_id: str = "network-telemetry",
        name: str = "Network Telemetry",
        credibility_prior: float = 0.55,
        extra_targets_file: str | Path | None = None,
    ) -> None:
        self.targets = [target.lower() for target in (targets or ["iran", "russia", "china"])]
        self.include_unfocused = include_unfocused
        self.source_id = source_id
        self.name = name
        self.credibility_prior = credibility_prior
        self.diagnostics: list[str] = []
        self._load_extra_targets(extra_targets_file)

    def _source(self) -> Source:
        return Source(
            id=self.source_id,
            name=self.name,
            source_type=SourceType.NETWORK_TELEMETRY,
            credibility_prior=self.credibility_prior,
            base_url="network://local-or-imported",
            config={
                "targets": self.targets,
                "include_unfocused": self.include_unfocused,
                "scope": "operator-authorized local or imported telemetry (rich flow/packet metadata accepted)",
            },
            tos_summary=(
                "Operator-authorized local/imported telemetry only. Ingress ingests metadata only. "
                "No packet capture, payload capture, remote probing, credential access, or third-party "
                "traffic interception is performed by this tool."
            ),
        )

    def _load_extra_targets(self, extra_targets_file: str | Path | None) -> None:
        if not extra_targets_file:
            return
        p = Path(extra_targets_file)
        if not p.exists():
            self.diagnostics.append(f"Extra network targets file not found: {p}")
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            for country in ("iran", "russia", "china"):
                extra = data.get(country, []) if isinstance(data, dict) else []
                if isinstance(extra, list):
                    current = list(TARGET_DOMAIN_SUFFIXES.get(country, ()))
                    for dom in extra:
                        if isinstance(dom, str) and dom not in current:
                            current.append(dom)
                    TARGET_DOMAIN_SUFFIXES[country] = tuple(current)
            self.diagnostics.append(f"Loaded extra network targets from {p}")
        except Exception as exc:
            self.diagnostics.append(f"Failed to load extra targets from {p}: {exc}")

    def collect_from_jsonl(self, path: str | Path, limit: int | None = None) -> list[Artifact]:
        records: list[dict[str, Any]] = []
        source_path = Path(path)
        if not source_path.exists():
            self.diagnostics.append(f"Input file not found: {source_path}. Create it or use --sample for a demo.")
            return []
        try:
            with source_path.open(encoding="utf-8") as fh:
                for line_number, line in enumerate(fh, start=1):
                    if limit is not None and len(records) >= limit:
                        break
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        loaded = json.loads(text)
                    except json.JSONDecodeError as exc:
                        self.diagnostics.append(f"{source_path}:{line_number}: invalid JSON: {exc}")
                        continue
                    if isinstance(loaded, dict):
                        loaded.setdefault("telemetry_source", str(source_path))
                        records.append(loaded)
                    else:
                        self.diagnostics.append(f"{source_path}:{line_number}: expected object")
        except Exception as exc:
            self.diagnostics.append(f"Failed to read {source_path}: {exc}")
            return []
        return self.collect_from_records(records, limit=limit)

    def collect_from_file(self, path: str | Path, *, format: str | None = None, limit: int | None = None) -> list[Artifact]:
        """
        Ingest from a file, with optional format hint for better normalization.

        Supported formats (auto-detected or via format=):
          - jsonl (generic, default)
          - zeek (conn.log, dns.log, ssl.log, http.log - TSV or JSON)
          - suricata (eve.json)
          - tshark-json (tshark -T json output)
          - pcap (requires tshark; delegates to CLI helper in practice)

        This makes Ingress a strong platform for authorized network telemetry
        from Zeek, Suricata, endpoint agents, commercial sensors, legal intercept
        outputs, etc.
        """
        p = Path(path)
        fmt = (format or "").lower()

        if fmt == "zeek" or p.suffix in {".log", ".tsv"} or "zeek" in p.name.lower():
            return self.collect_from_zeek(p, limit=limit)
        if fmt == "suricata" or "eve" in p.name.lower() or p.suffix == ".json":
            # Try Suricata first if it looks like eve
            try:
                return self.collect_from_suricata_eve(p, limit=limit)
            except Exception:
                pass  # fall through to generic jsonl
        if fmt in {"tshark", "tshark-json"}:
            return self.collect_from_tshark_json(p, limit=limit)

        # Default to generic JSONL (most flexible for custom/authorized sensors)
        return self.collect_from_jsonl(p, limit=limit)

    def collect_from_zeek(self, path: str | Path, limit: int | None = None) -> list[Artifact]:
        """Parse common Zeek logs (conn, dns, ssl, http) into normalized records."""
        records: list[dict[str, Any]] = []
        source_path = Path(path)
        if not source_path.exists():
            self.diagnostics.append(f"Zeek log not found: {source_path}")
            return []

        try:
            with source_path.open(encoding="utf-8", errors="replace") as fh:
                # Zeek logs often have #fields header
                fields: list[str] = []
                for line_number, line in enumerate(fh, start=1):
                    if limit is not None and len(records) >= limit:
                        break
                    line = line.strip()
                    if not line or line.startswith("#close") or line.startswith("#types"):
                        continue
                    if line.startswith("#fields"):
                        fields = line.split()[1:]
                        continue
                    if line.startswith("#"):
                        continue

                    parts = line.split("\t")
                    if not fields or len(parts) != len(fields):
                        # Fallback simple parse for some Zeek JSON exports
                        try:
                            obj = json.loads(line)
                            records.append(self._zeek_obj_to_record(obj, source_path))
                        except Exception:
                            continue
                        continue

                    rec = dict(zip(fields, parts))
                    records.append(self._zeek_obj_to_record(rec, source_path))
        except Exception as exc:
            self.diagnostics.append(f"Failed parsing Zeek log {source_path}: {exc}")

        return self.collect_from_records(records, limit=limit)

    def _zeek_obj_to_record(self, obj: dict, source_path: Path) -> dict[str, Any]:
        """Map Zeek conn/dns/ssl/http fields to our generic record shape."""
        rec: dict[str, Any] = {"telemetry_source": f"zeek:{source_path.name}"}
        # conn.log
        if "id.resp_h" in obj:
            rec["remote_host"] = obj.get("id.resp_h")
            rec["remote_port"] = obj.get("id.resp_p")
            rec["local_host"] = obj.get("id.orig_h")
            rec["local_port"] = obj.get("id.orig_p")
            rec["protocol"] = obj.get("proto", "tcp").lower()
            rec["state"] = obj.get("conn_state")
            if "orig_bytes" in obj:
                rec["bytes_sent"] = obj.get("orig_bytes")
            if "resp_bytes" in obj:
                rec["bytes_received"] = obj.get("resp_bytes")
            rec["duration"] = obj.get("duration")
        # dns.log
        if "query" in obj:
            rec["dns_query"] = obj.get("query")
            rec["remote_host"] = obj.get("answers") or obj.get("id.resp_h")
        # ssl.log
        if "server_name" in obj or "sni" in str(obj).lower():
            rec["sni"] = obj.get("server_name") or obj.get("sni")
            rec["remote_host"] = obj.get("id.resp_h")
        # http.log
        if "host" in obj:
            rec["http_host"] = obj.get("host")
            rec["remote_host"] = obj.get("id.resp_h")
        return rec

    def collect_from_suricata_eve(self, path: str | Path, limit: int | None = None) -> list[Artifact]:
        """Parse Suricata EVE JSON (flow, dns, tls, http events)."""
        records: list[dict[str, Any]] = []
        source_path = Path(path)
        if not source_path.exists():
            self.diagnostics.append(f"Suricata EVE file not found: {source_path}")
            return []

        try:
            with source_path.open(encoding="utf-8") as fh:
                for line_number, line in enumerate(fh, start=1):
                    if limit is not None and len(records) >= limit:
                        break
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        event = json.loads(text)
                    except json.JSONDecodeError:
                        continue

                    if event.get("event_type") in {"flow", "dns", "tls", "http"}:
                        rec = self._suricata_event_to_record(event, source_path)
                        if rec:
                            records.append(rec)
        except Exception as exc:
            self.diagnostics.append(f"Failed parsing Suricata EVE {source_path}: {exc}")

        return self.collect_from_records(records, limit=limit)

    def _suricata_event_to_record(self, event: dict, source_path: Path) -> dict[str, Any] | None:
        etype = event.get("event_type")
        src = event.get("src_ip") or event.get("source_ip")
        dst = event.get("dest_ip") or event.get("dst_ip")
        rec: dict[str, Any] = {
            "telemetry_source": f"suricata:{source_path.name}",
            "remote_host": dst,
            "local_host": src,
            "protocol": (event.get("proto") or "tcp").lower(),
        }
        if "src_port" in event:
            rec["local_port"] = event.get("src_port")
        if "dest_port" in event:
            rec["remote_port"] = event.get("dest_port")

        if etype == "dns":
            dns = event.get("dns", {})
            rec["dns_query"] = dns.get("rrname") or dns.get("query")
        elif etype == "tls":
            tls = event.get("tls", {})
            rec["sni"] = tls.get("sni")
        elif etype == "http":
            http = event.get("http", {})
            rec["http_host"] = http.get("hostname") or http.get("http_host")
        elif etype == "flow":
            flow = event.get("flow", {})
            rec["bytes_sent"] = flow.get("bytes_toserver")
            rec["bytes_received"] = flow.get("bytes_toclient")
            rec["state"] = flow.get("state")

        return rec if rec.get("remote_host") or rec.get("dns_query") or rec.get("sni") else None

    def collect_from_tshark_json(self, path: str | Path, limit: int | None = None) -> list[Artifact]:
        """Parse output from `tshark -T json` (array of packets with layers)."""
        records: list[dict[str, Any]] = []
        source_path = Path(path)
        if not source_path.exists():
            self.diagnostics.append(f"tshark JSON not found: {source_path}")
            return []

        try:
            data = json.loads(source_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data = data.get("_source", [data])  # sometimes wrapped

            for pkt in (data if isinstance(data, list) else [data]):
                layers = pkt.get("_source", {}).get("layers", {}) if isinstance(pkt, dict) else {}
                ip = layers.get("ip", {})
                tcp = layers.get("tcp", {})
                udp = layers.get("udp", {})
                dns = layers.get("dns", {})
                tls = layers.get("tls", {})
                http = layers.get("http", {})

                rec: dict[str, Any] = {
                    "telemetry_source": f"tshark-json:{source_path.name}",
                    "remote_host": ip.get("ip.dst") or ip.get("ip.dst_host"),
                    "local_host": ip.get("ip.src") or ip.get("ip.src_host"),
                    "remote_port": tcp.get("tcp.dstport") or udp.get("udp.dstport"),
                    "local_port": tcp.get("tcp.srcport") or udp.get("udp.srcport"),
                    "protocol": "tcp" if tcp else ("udp" if udp else "ip"),
                    "sni": tls.get("tls.handshake.extensions_server_name"),
                    "dns_query": dns.get("dns.qry.name"),
                    "http_host": http.get("http.host"),
                }
                rec = {k: v for k, v in rec.items() if v}
                if rec:
                    records.append(rec)
                    if limit is not None and len(records) >= limit:
                        break
        except Exception as exc:
            self.diagnostics.append(f"Failed parsing tshark JSON {source_path}: {exc}")

        return self.collect_from_records(records, limit=limit)

    def collect_from_records(
        self,
        records: list[dict[str, Any]],
        *,
        limit: int | None = None,
    ) -> list[Artifact]:
        artifacts: list[Artifact] = []
        source = self._source()
        for record in records:
            if limit is not None and len(artifacts) >= limit:
                break
            cleaned, warns = _sanitize_record(record)
            for w in warns:
                self.diagnostics.append(f"sanitize: {w}")
            artifact = self._record_to_artifact(cleaned, source)
            if artifact is not None:
                artifacts.append(artifact)
        return artifacts

    def collect_local_snapshot(self, limit: int | None = None) -> list[Artifact]:
        command = self._local_snapshot_command()
        if command is None:
            self.diagnostics.append("No supported local network snapshot command found (lsof, ss, or netstat).")
            return []
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=8, check=False)
        except Exception as exc:
            self.diagnostics.append(f"{' '.join(command)} failed: {exc}")
            return []
        if proc.returncode != 0 and not proc.stdout:
            self.diagnostics.append(proc.stderr.strip() or f"{' '.join(command)} exited {proc.returncode}")
            return []
        records = self._parse_snapshot_output(command[0], proc.stdout)
        return self.collect_from_records(records, limit=limit)

    def _local_snapshot_command(self) -> list[str] | None:
        if shutil.which("lsof"):
            return ["lsof", "-nP", "-iTCP", "-iUDP"]
        if shutil.which("ss"):
            return ["ss", "-tunp"]
        if shutil.which("netstat"):
            return ["netstat", "-an"]
        return None

    def _parse_snapshot_output(self, command_name: str, output: str) -> list[dict[str, Any]]:
        if command_name == "lsof":
            return self._parse_lsof(output)
        if command_name == "ss":
            return self._parse_ss(output)
        return self._parse_netstat(output)

    def _parse_lsof(self, output: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 9:
                continue
            name = " ".join(parts[8:])
            if "->" not in name:
                continue
            local, remote_state = name.split("->", 1)
            remote = remote_state.split()[0]
            state_match = re.search(r"\(([^)]*)\)", name)
            records.append({
                "timestamp": _utc_now().isoformat(),
                "process": parts[0],
                "pid": parts[1],
                "protocol": "tcp" if "TCP" in name.upper() else "udp",
                "local": local,
                "remote": remote,
                "state": state_match.group(1).lower() if state_match else "",
                "telemetry_source": "lsof",
            })
        return records

    def _parse_ss(self, output: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 6 or parts[0].lower() not in {"tcp", "udp"}:
                continue
            process_match = re.search(r'"([^"]+)"', line)
            records.append({
                "timestamp": _utc_now().isoformat(),
                "protocol": parts[0].lower(),
                "state": parts[1].lower(),
                "local": parts[4],
                "remote": parts[5],
                "process": process_match.group(1) if process_match else None,
                "telemetry_source": "ss",
            })
        return records

    def _parse_netstat(self, output: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 5 or not parts[0].lower().startswith(("tcp", "udp")):
                continue
            records.append({
                "timestamp": _utc_now().isoformat(),
                "protocol": parts[0].lower(),
                "local": parts[3],
                "remote": parts[4],
                "state": parts[5].lower() if len(parts) > 5 else "",
                "telemetry_source": "netstat",
            })
        return records

    def _record_to_artifact(self, record: dict[str, Any], source: Source) -> Artifact | None:
        remote_value = _first_present(record, RECORD_REMOTE_FIELDS)
        remote_host, parsed_remote_port = split_endpoint(remote_value)
        remote_port = _coerce_port(record.get("remote_port") or record.get("dst_port")) or parsed_remote_port
        remote_domain = normalize_domain(
            record.get("remote_domain")
            or record.get("domain")
            or record.get("server_name")
            or record.get("sni")
            or record.get("tls_sni")
            or record.get("query")
            or record.get("dns_query")
            or record.get("url")
            or remote_value
        )
        if remote_domain:
            remote_host = remote_domain

        if not is_public_host(remote_host):
            return None

        local_host, parsed_local_port = split_endpoint(record.get("local") or record.get("local_host") or record.get("src"))
        local_port = _coerce_port(record.get("local_port") or record.get("src_port")) or parsed_local_port
        target_countries, indicators = infer_network_targets(record, remote_domain, remote_host)
        if self.targets:
            target_countries = [target for target in target_countries if target in self.targets]
        if not target_countries and not self.include_unfocused:
            return None

        timestamp = _record_timestamp(record)
        protocol = str(record.get("protocol") or record.get("proto") or "tcp").lower()
        process = _record_process(record)
        state = str(record.get("state") or record.get("event_type") or "observed")
        endpoint = remote_domain or remote_host or "unknown"
        port_label = f":{remote_port}" if remote_port is not None else ""
        target_label = ", ".join(target.title() for target in target_countries) or "unfocused public domain"
        text = (
            f"Network observation: {protocol.upper()} connection or flow to {endpoint}{port_label} "
            f"matched {target_label}. State={state}."
        )
        if process:
            text += f" Process={process}."

        # Enrich with fields typical of packet/flow/DNS/TLS telemetry (authorized sources)
        enrich: dict[str, Any] = {}
        for key in RECORD_ENRICH_FIELDS:
            val = record.get(key)
            if val not in (None, ""):
                # Avoid duplicating core fields already promoted
                if key in ("sni", "tls_sni", "server_name", "query", "dns_query") and val == remote_domain:
                    continue
                enrich[key] = val

        if enrich:
            # Append high-value hints to the analyst-facing text (no raw content)
            hints = []
            if "ja3" in enrich or "ja3s" in enrich:
                hints.append("ja3-fp")
            if any(k in enrich for k in ("bytes", "bytes_sent", "bytes_received", "orig_bytes", "resp_bytes")):
                hints.append("bytes")
            if any(k in enrich for k in ("duration", "duration_ms")):
                hints.append("dur")
            if "http_host" in enrich or "host" in enrich:
                hints.append("http")
            if "dns_query" in enrich or "query" in enrich:
                hints.append("dns")
            if hints:
                text += f" [{','.join(hints)}]"
            text += " (enriched from flow/packet metadata)"
        else:
            text += " Scope=operator-authorized local/imported telemetry; no packet content captured."

        canonical = {
            "timestamp": timestamp.isoformat(),
            "protocol": protocol,
            "remote_host": remote_host,
            "remote_domain": remote_domain,
            "remote_port": remote_port,
            "local_host": local_host,
            "local_port": local_port,
            "process": process,
            "pid": record.get("pid"),
            "state": state,
            "target_countries": target_countries,
            "telemetry_source": record.get("telemetry_source"),
        }
        # include a stable subset of enrich for hash stability (fingerprint/volume useful for correlation)
        if enrich:
            for ek in ("ja3", "ja3s", "dns_query", "http_host", "bytes_sent", "bytes_received", "duration"):
                if ek in enrich:
                    canonical[ek] = enrich[ek]
        canonical_text = json.dumps(canonical, sort_keys=True, default=str)
        content_hash = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
        raw_ref = f"network://{endpoint}{port_label}"

        provenance = ProvenanceEntry(
            source_id=source.id,
            source_type=SourceType.NETWORK_TELEMETRY,
            url_or_id=raw_ref,
            fetched_at=_utc_now(),
            collector="network-telemetry-collector",
            collector_version="0.2.0",
            content_hash=content_hash,
            tos_compliant=True,
        )

        metadata = {
            "network_monitor": True,
            "monitor_scope": (
                "operator-authorized local/imported telemetry; supports richer flow/packet-derived "
                "metadata (SNI, JA3, DNS, HTTP host, byte counts, etc.) from authorized external tools"
            ),
            "remote_host": remote_host,
            "remote_domain": remote_domain,
            "remote_port": remote_port,
            "local_host": local_host,
            "local_port": local_port,
            "protocol": protocol,
            "process": process,
            "pid": record.get("pid"),
            "state": state,
            "telemetry_source": record.get("telemetry_source") or "local-snapshot",
            "target_countries": target_countries,
            "matched_network_indicators": indicators,
            "entities": [item for item in [endpoint, protocol, process] if item],
            "confidence": 0.62 if target_countries else 0.42,
            "status": "unverified",
            "verification_status": "unverified",
            "compatibility_schema": "ingress.network_telemetry.v1",
        }
        if enrich:
            metadata["enriched"] = enrich
            # promote a few top-level for convenience in API / watch
            for ek in ("ja3", "ja3s", "http_host", "dns_query", "bytes_sent", "bytes_received", "duration"):
                if ek in enrich and ek not in metadata:
                    metadata[ek] = enrich[ek]
        if len(target_countries) == 1:
            metadata["target_country"] = target_countries[0]

        return Artifact(
            source=source,
            provenance=[provenance],
            content_type="network_telemetry",
            raw_ref=raw_ref,
            content_hash=content_hash,
            fetched_at=timestamp,
            text=text,
            metadata=metadata,
        )
