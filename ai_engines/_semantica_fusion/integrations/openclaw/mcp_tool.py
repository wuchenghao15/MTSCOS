"""
OpenClaw ↔ Semantica bridge
============================

Two integration paths:

1. **MCP (recommended)** — ``OpenClawMCPConfig`` emits the ``mcporter.json``
   snippet that wires Semantica's MCP server into the OpenClaw Gateway.
   All 15 Semantica MCP tools become native OpenClaw agent tools with no
   extra code.

2. **REST** — ``OpenClawKGTool`` is a plain Python class that calls the
   Semantica REST API (port 8000) and can be registered as an OpenClaw
   native tool via SOUL.md ``tools:`` entries.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# MCP config helper
# ---------------------------------------------------------------------------

class OpenClawMCPConfig:
    """
    Generates the ``mcporter.json`` entry needed to connect Semantica's MCP
    server to the OpenClaw Gateway.

    Parameters
    ----------
    server_command:
        Shell command used to launch the Semantica MCP server.
        Defaults to ``"python -m semantica.mcp_server"``.
    transport:
        MCP transport protocol.  OpenClaw supports ``"stdio"`` (default)
        and ``"sse"``.
    name:
        Key used in ``mcporter.json``.  Defaults to ``"semantica"``.

    Example
    -------
    >>> cfg = OpenClawMCPConfig()
    >>> print(cfg.to_json())
    # → paste into ~/.openclaw/mcporter.json, then:
    # → openclaw gateway restart
    """

    def __init__(
        self,
        server_command: str = "python -m semantica.mcp_server",
        transport: str = "stdio",
        name: str = "semantica",
    ) -> None:
        self.server_command = server_command
        self.transport = transport
        self.name = name

    def to_dict(self) -> Dict[str, Any]:
        """Return the config as a plain dict."""
        parts = self.server_command.split()
        return {
            "mcpServers": {
                self.name: {
                    "command": parts[0],
                    "args": parts[1:],
                    "transport": self.transport,
                }
            }
        }

    def to_json(self, indent: int = 2) -> str:
        """Return the config as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def __repr__(self) -> str:  # pragma: no cover
        return f"OpenClawMCPConfig(name={self.name!r}, transport={self.transport!r})"


# ---------------------------------------------------------------------------
# REST-based native tool
# ---------------------------------------------------------------------------

class OpenClawKGTool:
    """
    A Semantica knowledge-graph tool callable from an OpenClaw agent.

    Wraps the Semantica REST API so that an OpenClaw agent configured with
    this tool (via SOUL.md ``tools:`` entries or programmatic registration)
    can extract entities, record decisions, query the graph, and more —
    without requiring the MCP gateway.

    Parameters
    ----------
    base_url:
        Base URL of the running Semantica REST server.
        Defaults to ``"http://localhost:8000"``.
    timeout:
        Request timeout in seconds.  Defaults to ``30``.

    Notes
    -----
    ``requests`` is used for HTTP calls.  It is listed as an optional
    dependency under ``semantica[openclaw]``; install it with::

        pip install semantica[openclaw]
    """

    TOOL_NAME = "semantica_kg"
    TOOL_DESCRIPTION = (
        "Semantica knowledge-graph tool. "
        "Supports entity extraction, decision recording, graph querying, "
        "causal chain analysis, reasoning, and multi-format export."
    )

    # ------------------------------------------------------------------
    # SSRF guard — shared by both the semantica.ingest path and the
    # fallback path when semantica.ingest is not installed.
    # ------------------------------------------------------------------

    # Hostnames that must never be called (even with allow_private_ips=True)
    _SSRF_HOSTNAME_BLACKLIST = frozenset({
        "0.0.0.0",           # wildcard bind-all
        "169.254.169.254",   # AWS/GCP/Azure 云元数据
        "metadata.google.internal",
        "metadata",          # GCP instance metadata hostname
    })

    # Private/link-local/reserved IP ranges (CIDR) — any of these in the
    # hostname (after DNS resolution) must be rejected unless the resolved
    # host is explicitly "localhost" or "127.0.0.1".
    _SSRF_BLOCKED_CIDRS = [
        ("10.0.0.0", 8),
        ("172.16.0.0", 12),
        ("192.168.0.0", 16),
        ("127.0.0.0", 8),      # loopback (but localhost → 127.0.0.1 is OK)
        ("169.254.0.0", 16),  # link-local (includes 169.254.169.254)
        ("0.0.0.0", 8),       # current network
        ("100.64.0.0", 10),   # CGNAT
        ("198.18.0.0", 15),   # benchmarking reserved
    ]

    @classmethod
    def _ip_in_cidr(cls, ip: str) -> bool:
        """Return True if *ip* falls in any blocked CIDR range."""
        try:
            import ipaddress
            addr = ipaddress.ip_address(ip)
            for network, prefix_len in cls._SSRF_BLOCKED_CIDRS:
                net = ipaddress.ip_network(f"{network}/{prefix_len}", strict=False)
                if addr in net:
                    return True
        except (ValueError, TypeError):
            pass
        return False

    @classmethod
    def _fallback_ssrf_validate(cls, base_url: str) -> str:
        """
        Mirrors ``semantica.ingest.ssrf.validate_url_for_request`` when the
        semantica package is not installed.  Performs the same structural +
        hostname + CIDR checks — but **still rejects** localhost variants
        that happen to resolve to private IPs (we intentionally do *not*
        allow_private_ips in this fallback because we don't know the user's
        exact intent; callers who want to allow private IPs should install
        semantica.ingest and use the primary path).
        """
        from urllib.parse import urlparse as _urlparse

        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("OpenClawKGTool base_url must be a non-empty string.")

        _parsed = _urlparse(base_url.strip())

        _scheme = (_parsed.scheme or "").lower()
        if _scheme not in ("http", "https"):
            raise ValueError(
                f"OpenClawKGTool base_url scheme '{_parsed.scheme}' is not permitted. "
                "Only http and https are allowed."
            )

        if not _parsed.netloc:
            raise ValueError(
                f"Invalid OpenClawKGTool base_url '{base_url}': "
                "URL must include a netloc (domain or host)."
            )

        _hostname = (_parsed.hostname or "").lower()
        if not _hostname:
            raise ValueError(
                f"Invalid OpenClawKGTool base_url '{base_url}': "
                "URL must include a hostname."
            )

        # 1) Exact hostname blacklist
        if _hostname in cls._SSRF_HOSTNAME_BLACKLIST:
            raise ValueError(
                f"OpenClawKGTool base_url hostname '{_hostname}' is blocked by SSRF guard."
            )

        # 2) "localhost" is the documented default for local Semantica dev — allow it
        #    through the CIDR filter.  IP-literal forms (127.0.0.1, ::1) still blocked.
        if _hostname == "localhost":
            return base_url.strip()

        # 3) IP-based check (if the hostname is an IP literal)
        if cls._ip_in_cidr(_hostname):
            raise ValueError(
                f"OpenClawKGTool base_url hostname '{_hostname}' resolves to a private/"
                "reserved IP range and is blocked by SSRF guard."
            )

        return base_url.strip()

    def __init__(self, base_url: str = "http://localhost:8000", timeout: int = 30) -> None:
        # Validate base_url at construction time so callers get an immediate,
        # actionable error rather than a cryptic failure on the first request.
        try:
            from semantica.ingest.ssrf import validate_url_for_request
            validated = validate_url_for_request(base_url, allow_private_ips=True)
        except ImportError:
            # semantica.ingest not installed in minimal openclaw-only environments;
            # use our own fallback validator which mirrors the scheme + netloc +
            # hostname checks, plus hostname blacklist + CIDR filtering.
            validated = self._fallback_ssrf_validate(base_url)

        self.base_url = validated.rstrip("/")
        self.timeout = timeout
        self._session: Any = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_session(self) -> Any:
        if self._session is None:
            try:
                import requests
                self._session = requests.Session()
            except ImportError as exc:
                raise ImportError(
                    "The 'requests' package is required for OpenClawKGTool. "
                    "Install it with: pip install semantica[openclaw]"
                ) from exc
        return self._session

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        session = self._get_session()
        url = f"{self.base_url}{endpoint}"
        response = session.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        session = self._get_session()
        url = f"{self.base_url}{endpoint}"
        response = session.get(url, params=params or {}, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def extract(self, text: str) -> Dict[str, Any]:
        """Extract entities and relations from *text*."""
        return self._post("/extract", {"text": text})

    def extract_entities(self, text: str) -> List[Dict[str, Any]]:
        """Return only the entity list from *text*."""
        result = self.extract(text)
        return result.get("entities", [])

    def extract_relations(self, text: str) -> List[Dict[str, Any]]:
        """Return only the relation list from *text*."""
        result = self.extract(text)
        return result.get("relations", [])

    # ------------------------------------------------------------------
    # Graph mutation
    # ------------------------------------------------------------------

    def add_entity(self, label: str, entity_type: str = "Entity", **properties: Any) -> Dict[str, Any]:
        """Add a node to the knowledge graph."""
        return self._post("/entities", {"label": label, "type": entity_type, **properties})

    def add_relationship(
        self,
        source: str,
        target: str,
        relation_type: str,
        **properties: Any,
    ) -> Dict[str, Any]:
        """Add an edge between *source* and *target*."""
        return self._post(
            "/relationships",
            {"source": source, "target": target, "type": relation_type, **properties},
        )

    # ------------------------------------------------------------------
    # Decisions
    # ------------------------------------------------------------------

    def record_decision(
        self,
        decision_text: str,
        context: Optional[str] = None,
        **metadata: Any,
    ) -> Dict[str, Any]:
        """Record a decision in the graph."""
        payload: Dict[str, Any] = {"decision": decision_text}
        if context:
            payload["context"] = context
        payload.update(metadata)
        return self._post("/decisions", payload)

    def query_decisions(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search recorded decisions."""
        result = self._get("/decisions/search", {"q": query, "limit": limit})
        return result.get("decisions", [])

    def find_precedents(self, decision_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Find past decisions similar to *decision_text*."""
        result = self._post("/decisions/precedents", {"decision": decision_text, "top_k": top_k})
        return result.get("precedents", [])

    # ------------------------------------------------------------------
    # Analytics & reasoning
    # ------------------------------------------------------------------

    def get_causal_chain(self, node_id: str, depth: int = 3) -> Dict[str, Any]:
        """Retrieve the causal chain rooted at *node_id*."""
        return self._get("/causal-chain", {"node_id": node_id, "depth": depth})

    def run_reasoning(self, rules: List[str], facts: List[str]) -> Dict[str, Any]:
        """Run the Semantica forward-chaining reasoner."""
        return self._post("/reason", {"rules": rules, "facts": facts})

    def get_graph_analytics(self) -> Dict[str, Any]:
        """Return graph-level analytics (centrality, communities, etc.)."""
        return self._get("/analytics")

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_graph(self, fmt: str = "json") -> str:
        """Export the graph in *fmt* (``json``, ``ttl``, ``graphml``, …)."""
        result = self._get("/export", {"format": fmt})
        return result.get("data", "")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_graph_summary(self) -> Dict[str, Any]:
        """Return a high-level summary of the current graph."""
        return self._get("/graph/summary")

    def __repr__(self) -> str:  # pragma: no cover
        return f"OpenClawKGTool(base_url={self.base_url!r})"
