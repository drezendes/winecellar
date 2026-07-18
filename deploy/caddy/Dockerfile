# Custom Caddy: Cloudflare DNS-01 (orange-cloud-safe TLS) + Cloudflare
# trusted_proxies (real client IPs behind the CF proxy). Built on the box
# (arm64) — both stages are multi-arch.
FROM caddy:2-builder AS build
RUN xcaddy build \
    --with github.com/caddy-dns/cloudflare \
    --with github.com/WeidiDeng/caddy-cloudflare-ip

FROM caddy:2
COPY --from=build /usr/bin/caddy /usr/bin/caddy
