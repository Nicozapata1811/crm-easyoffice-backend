FROM docker.io/cloudflare/cloudflared:2026.10.0 AS cloudflared

FROM docker.io/library/alpine:3.22
RUN apk add --no-cache ca-certificates
COPY --from=cloudflared /usr/local/bin/cloudflared /usr/local/bin/cloudflared
COPY --chmod=755 start-tunnel.sh /usr/local/bin/start-tunnel
USER 65532
ENTRYPOINT ["start-tunnel"]
