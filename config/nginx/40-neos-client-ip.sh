#!/bin/sh
# Writes the map that decides whether nginx trusts X-Neos-Client-IP.
#
# nginx:alpine runs every executable /docker-entrypoint.d/*.sh before it starts,
# so docker-compose.enterprise.yml mounts this file there. nginx.conf includes
# the output and keys both rate limits on $client_rate_key.
#
# The web BFF (Vercel) sends the end user's IP in X-Neos-Client-IP and the shared
# secret in X-Neos-Proxy-Auth (web/lib/client-ip.ts). Only a matching secret makes
# nginx count that IP; everything else is counted by the TCP peer as before.
#
# The map is generated instead of written into nginx.conf because an unset secret
# would otherwise render as "" and match every request that omits the header,
# letting anyone pick their own rate-limit bucket. No secret -> trust nothing.
# A malformed secret stops the container rather than silently trusting nothing.
set -eu

out="${NEOS_NGINX_CONF_D:-/etc/nginx/conf.d}/neos-client-ip.conf"
secret="${NEOS_CLIENT_IP_SECRET:-}"

if [ -z "$secret" ]; then
    echo "40-neos-client-ip: NEOS_CLIENT_IP_SECRET unset; X-Neos-Client-IP is ignored" >&2
    mkdir -p "$(dirname "$out")"
    printf 'map $http_x_neos_proxy_auth $neos_proxy_trusted {\n    default 0;\n}\n' > "$out"
    exit 0
fi

case "$secret" in
    *[!A-Za-z0-9_-]*)
        echo "40-neos-client-ip: NEOS_CLIENT_IP_SECRET may only use [A-Za-z0-9_-]" >&2
        exit 1
        ;;
esac
if [ "${#secret}" -lt 32 ]; then
    echo "40-neos-client-ip: NEOS_CLIENT_IP_SECRET must be at least 32 characters" >&2
    exit 1
fi

mkdir -p "$(dirname "$out")"
printf 'map $http_x_neos_proxy_auth $neos_proxy_trusted {\n    default 0;\n    "%s" 1;\n}\n' "$secret" > "$out"
