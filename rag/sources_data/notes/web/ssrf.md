domain: web

# Server-Side Request Forgery (SSRF)

SSRF is a vulnerability where an attacker induces the server-side application to
make HTTP requests to an arbitrary domain of the attacker's choosing. Typical
targets are the loopback interface (127.0.0.1), internal-only services, and
cloud metadata endpoints such as 169.254.169.254.

Common vectors: a URL parameter the server fetches (webhooks, PDF generators,
image proxies, link previews), XML external entities, and open redirects
chained into a fetch.

Defenses: enforce an allowlist of destination hosts and schemes, resolve and
re-check the IP after DNS resolution (guard against rebinding), block link-local
and private ranges, disable unused URL schemes, and never send raw upstream
responses back to the client.
