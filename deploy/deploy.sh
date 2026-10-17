#!/usr/bin/env bash
# @exports: deploy/deploy.sh  (no args; run from anywhere, uses repo root)
# @imports: deploy/Dockerfile, .env, sayable/mcp_client.py (CLI wait), sayable/lint.py (CLI)
# @env: HOSTED_URL
# @env: CONFIRM_SECRET
# @env: CONFIRM_THRESHOLD
# @env: PANTRY_ALLOWED_HOSTS
# @env: PANTRY_PORT
# @schema: HOSTED_URL must be https://<host>/mcp ; <host> must be listed in PANTRY_ALLOWED_HOSTS
# @schema: containers: sayable-pantry (private docker network sayable-net, no published port), sayable-caddy (80/443, TLS, per-IP rate limit via caddy-ratelimit)
# @schema: volumes: sayable-data (/app/data), sayable-caddy-data, sayable-caddy-config ; generated Caddyfile: data/Caddyfile
# @schema: cron (current user): hourly `docker exec sayable-pantry python -m pantry.db reset --path /app/data/pantry.db`
# Only the voice-first Pantry server is exposed. Its data is a non-sensitive fixture.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

die() { echo "FAIL deploy: $*" >&2; exit 1; }

[ -f .env ] || die ".env not found. Copy .env.example to .env and fill it in."
set -a; . ./.env; set +a

need() { [ -n "${!1:-}" ] || die "$1 is not set in .env (see .env.example)."; }
need HOSTED_URL
need CONFIRM_SECRET
need CONFIRM_THRESHOLD
need PANTRY_ALLOWED_HOSTS
need PANTRY_PORT

command -v docker >/dev/null 2>&1 || die "docker is not installed or not on PATH."
if [ -x .venv/bin/python ]; then PY=".venv/bin/python"; else PY="python3"; fi

HOST="$("$PY" -c 'import sys, urllib.parse as u
p = u.urlparse(sys.argv[1])
if p.scheme != "https" or not p.hostname or not p.path.startswith("/"):
    sys.exit("HOSTED_URL must look like https://your.domain/mcp")
print(p.hostname)' "$HOSTED_URL")" || die "HOSTED_URL is invalid: $HOSTED_URL"

case ",$PANTRY_ALLOWED_HOSTS," in
  *",$HOST,"*|*",$HOST:"*) ;;
  *) die "PANTRY_ALLOWED_HOSTS ($PANTRY_ALLOWED_HOSTS) must include $HOST, otherwise the server rejects its own domain." ;;
esac

echo "== network and volumes"
docker network inspect sayable-net >/dev/null 2>&1 || docker network create sayable-net >/dev/null
docker volume create sayable-data >/dev/null
docker volume create sayable-caddy-data >/dev/null
docker volume create sayable-caddy-config >/dev/null

echo "== building sayable-pantry"
docker build -f deploy/Dockerfile -t sayable-pantry .

echo "== building sayable-caddy (stock Caddy has no rate limiter, so build with caddy-ratelimit)"
docker build -t sayable-caddy - <<'EOF'
FROM caddy:2.8.4-builder AS builder
RUN xcaddy build --with github.com/mholt/caddy-ratelimit
FROM caddy:2.8.4
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
EOF

echo "== writing data/Caddyfile for $HOST"
mkdir -p data
cat > data/Caddyfile <<EOF
$HOST {
	route {
		rate_limit {
			zone per_ip {
				key {remote_host}
				events 120
				window 1m
			}
		}
		reverse_proxy sayable-pantry:$PANTRY_PORT {
			flush_interval -1
		}
	}
}
EOF

echo "== (re)starting containers"
docker rm -f sayable-pantry sayable-caddy >/dev/null
docker run -d --name sayable-pantry --restart unless-stopped --network sayable-net \
  -v sayable-data:/app/data \
  -e PANTRY_PORT="$PANTRY_PORT" \
  -e PANTRY_DB=/app/data/pantry.db \
  -e CONFIRM_SECRET="$CONFIRM_SECRET" \
  -e CONFIRM_THRESHOLD="$CONFIRM_THRESHOLD" \
  -e PANTRY_ALLOWED_HOSTS="$PANTRY_ALLOWED_HOSTS" \
  sayable-pantry >/dev/null
docker run -d --name sayable-caddy --restart unless-stopped --network sayable-net \
  -p 80:80 -p 443:443 \
  -v "$ROOT/data/Caddyfile:/etc/caddy/Caddyfile:ro" \
  -v sayable-caddy-data:/data -v sayable-caddy-config:/config \
  sayable-caddy >/dev/null

echo "== seeding the fixture database"
RESET_CMD="docker exec sayable-pantry python -m pantry.db reset --path /app/data/pantry.db"
$RESET_CMD

echo "== installing hourly reset in the current user's crontab"
( crontab -l 2>/dev/null | grep -v 'sayable-pantry-reset' || true; echo "0 * * * * $RESET_CMD >/dev/null 2>&1 # sayable-pantry-reset" ) | crontab -

echo "== waiting for $HOSTED_URL (first start needs time for the TLS certificate)"
ready=0
for _ in $(seq 1 60); do
  if "$PY" -m sayable.mcp_client "$HOSTED_URL" >/dev/null 2>&1; then ready=1; break; fi
  sleep 2
done
[ "$ready" -eq 1 ] || { docker logs --tail 30 sayable-caddy >&2; docker logs --tail 30 sayable-pantry >&2; die "$HOSTED_URL did not answer an MCP initialize within 120 s. Check DNS for $HOST, ports 80/443, and the logs above."; }

echo "== linting the hosted endpoint"
"$PY" -m sayable.lint "$HOSTED_URL" --probe-args eval/probe_args.json --min-score 85 --out results/lint_hosted.json --html results/lint_hosted.html
echo "OK deployed: $HOSTED_URL"
