"""`neos-sandboxd`: guest daemon protocol and its host-side client.

`guest.py` is the stdlib-only daemon baked into managed sandbox images.
`client.py` speaks its framed RPC and verifies the handshake; `session.py`
implements `SandboxSession` over it; `local.py` runs the daemon as a local
subprocess for tests and development.
"""
