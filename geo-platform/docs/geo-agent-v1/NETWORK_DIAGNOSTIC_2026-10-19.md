# GEO Agent V1 DeepSeek network diagnostic — 2026-10-19

## Scope and safety

This diagnostic followed the stop condition after the failed context-repair run. It made no
Agent, GEO, Workflow or budget-ledger change. It did not call `POST /responses`, did not send
an API key or `Authorization` header, and did not initiate model inference. The only external
HTTP operations were `HEAD https://api.deepseek.com/` and an unauthenticated
`GET https://api.deepseek.com/models`.

The structured, redacted probe log is preserved in
`docs/geo-agent-v1/NETWORK_DIAGNOSTIC_EVIDENCE_2026-10-19.json`.

This is an `IMPLEMENTATION_CHANGE` investigation with no implementation change and no
semantic-contract change.

## Runtime configuration checked

The probes used the same Python interpreter and installed HTTPX package used by the local
worker invocation:

- Python executable: `/Users/bmwqr/Desktop/python/GEO/geo-platform/backend/.venv/bin/python`
- Python: `3.14.3`
- HTTPX: `0.28.1`
- configured base URL: `https://api.deepseek.com`
- Agent endpoint: `https://api.deepseek.com/responses`
- configured timeout: 120 seconds
- Agent client retry setting: `max_attempts=1`
- API key configuration: present, but the value was neither read into diagnostic output nor
  transmitted by the probes

No upper- or lower-case HTTP proxy variables were present. `SSL_CERT_FILE`, `SSL_CERT_DIR`,
`REQUESTS_CA_BUNDLE` and `CURL_CA_BUNDLE` were also absent. The Python framework's advertised
OpenSSL CA file and directory do not exist, while the virtual environment's Certifi bundle
does exist. This is not the cause of the Agent failure: the application uses HTTPX, and the
HTTPX probes completed certificate verification successfully with its normal defaults.

## Reproduction and isolation

### Restricted execution environment

In the same default restricted execution context as the failed paid attempt:

- DNS failed with `socket.gaierror: [Errno 8] nodename nor servname provided, or not known`.
- TCP and TLS did not start because hostname resolution had already failed.
- HTTPX raised `httpx.ConnectError`, caused by `httpcore.ConnectError`, caused by that same
  `socket.gaierror`.
- `trust_env=True` and `trust_env=False` failed identically, excluding a proxy-environment
  difference as the cause.

This reproduces the exact outer exception class recorded by the failed Agent run and identifies
the previously hidden failure stage as DNS resolution before any provider connection.

### Network-enabled execution environment

The identical interpreter and target were then probed with network access explicitly enabled:

- DNS succeeded with two IPv4 addresses.
- TCP connection to port 443 succeeded.
- TLS negotiation succeeded with TLS 1.3 and `TLS_AES_256_GCM_SHA384`; the peer certificate
  was present, verified, and expires on 2026-12-01.
- HTTPX `HEAD /` succeeded at the transport layer and returned HTTP 401 with both
  `trust_env=True` and `trust_env=False`.
- HTTPX unauthenticated `GET /models` succeeded at the transport layer and returned HTTP 401,
  as expected without credentials.

An HTTP 401 is the expected useful result for these probes: it proves DNS, TCP, TLS and the
DeepSeek API authentication edge were reachable without authorizing or executing inference.

## Root cause and disposition

The failed Agent request was blocked by the restricted command environment's network policy at
DNS resolution. The evidence does not indicate a DeepSeek outage, bad API host, proxy issue,
TLS/CA failure or Agent decision-loop failure. No application code or configuration repair is
needed.

Any future authorized paid retry must run the existing worker command in a network-enabled
execution context. That operational permission is the minimal correction. It must not be
implemented by disabling TLS verification or by changing Agent business logic. This diagnostic
does not authorize such a retry.

## Preserved experiment state

Read-only inspection after the probes confirmed:

- failed Run: `agent-run-50a60949-2e4e-41d1-b486-7abd2016e7b2`
- status/blocker: `FAILED / AGENT_MODEL_UNAVAILABLE`
- frozen input scope hash still matches
  `69a86f8ecdc574e5a7631d6982270e1a25e29485937df4c17d2205ed99a7b2c7`
- model calls/tool calls/result versions: `0 / 0 / 0`
- last ledger request: `DELIVERY_UNKNOWN`, 31,172 accounted tokens and CNY 0.31172
- shared ledger: 14/36 requests, 110,913/3,000,000 accounted tokens and CNY 1.10913/30
- remaining shared capacity: 22 requests, 2,889,087 tokens and CNY 28.89087
- in-flight requests: 0

The unknown reservation was not released or reclassified. No second scenario and no new paid
request was started. Agent/Workflow quality remains `NOT_MEASURABLE` until a separately
authorized run produces a complete Agent result.

Evidence artifact hashes after the read-only checks:

- shared ledger SHA-256:
  `55e3f29ac88272dc65f948a87b37609f0b1b59f2d3d01824ac131f403d9793e8`
- isolated experiment database SHA-256:
  `e66a4b04e8cc7ebb6a49b19efe5c40ee383c2bc288fd85c3cff4b320d2d5739e`
