#!/usr/bin/env bash
# Generate self-signed CA + server/client certs for edu-ml K8s (Redis/Postgres mTLS + Ingress).
# Run in Git Bash or WSL:  bash scripts/generate-k8s-tls-certs.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${ROOT}/certs"
DAYS=825
CA_CN="edu-ml-ca"

mkdir -p "${OUT}"

gen_ca() {
  openssl genrsa -out "${OUT}/ca.key" 4096
  openssl req -x509 -new -nodes -key "${OUT}/ca.key" -sha256 -days "${DAYS}" \
    -out "${OUT}/ca.crt" -subj "/CN=${CA_CN}"
}

gen_server() {
  local name="$1"
  local cn="$2"
  openssl genrsa -out "${OUT}/${name}-server.key" 2048
  openssl req -new -key "${OUT}/${name}-server.key" -out "${OUT}/${name}-server.csr" \
    -subj "/CN=${cn}"
  openssl x509 -req -in "${OUT}/${name}-server.csr" -CA "${OUT}/ca.crt" -CAkey "${OUT}/ca.key" \
    -CAcreateserial -out "${OUT}/${name}-server.crt" -days "${DAYS}" -sha256
}

gen_client() {
  local name="$1"
  local cn="$2"
  openssl genrsa -out "${OUT}/${name}-client.key" 2048
  openssl req -new -key "${OUT}/${name}-client.key" -out "${OUT}/${name}-client.csr" \
    -subj "/CN=${cn}"
  openssl x509 -req -in "${OUT}/${name}-client.csr" -CA "${OUT}/ca.crt" -CAkey "${OUT}/ca.key" \
    -CAcreateserial -out "${OUT}/${name}-client.crt" -days "${DAYS}" -sha256
}

gen_ingress() {
  local cn="${INGRESS_HOST:-cpu-test2clusteres.ru}"
  local ip="${INGRESS_IP:-}"
  local san="DNS:${cn},DNS:localhost,IP:127.0.0.1"
  if [[ -n "${ip}" ]]; then
    san="${san},IP:${ip}"
  fi
  openssl genrsa -out "${OUT}/api.key" 2048
  openssl req -new -key "${OUT}/api.key" -out "${OUT}/api.csr" -subj "/CN=${cn}"
  printf "subjectAltName=%s\n" "${san}" > "${OUT}/api.ext"
  openssl x509 -req -in "${OUT}/api.csr" -CA "${OUT}/ca.crt" -CAkey "${OUT}/ca.key" \
    -CAcreateserial -out "${OUT}/api.crt" -days "${DAYS}" -sha256 \
    -extfile "${OUT}/api.ext"
  rm -f "${OUT}/api.ext" "${OUT}/api.csr"
}

echo "Generating CA..."
gen_ca
echo "Generating Redis server cert..."
gen_server redis redis.edu-ml.svc
echo "Generating Postgres server cert..."
gen_server postgres postgres.edu-ml.svc
echo "Generating Redis client cert..."
gen_client redis-client edu-ml-redis-client
echo "Generating Postgres client cert..."
gen_client postgres-client edu-ml-postgres-client
echo "Generating Ingress cert (${INGRESS_HOST:-cpu-test2clusteres.ru}${INGRESS_IP:+, IP ${INGRESS_IP}})..."
gen_ingress

# K8s secret-friendly copies (expected key names in manifests)
cp "${OUT}/redis-server.crt" "${OUT}/redis-tls.crt"
cp "${OUT}/redis-server.key" "${OUT}/redis-tls.key"
cp "${OUT}/postgres-server.crt" "${OUT}/postgres-tls.crt"
cp "${OUT}/postgres-server.key" "${OUT}/postgres-tls.key"
cp "${OUT}/redis-client-client.crt" "${OUT}/redis-client-tls.crt"
cp "${OUT}/redis-client-client.key" "${OUT}/redis-client-tls.key"
cp "${OUT}/postgres-client-client.crt" "${OUT}/postgres-client-tls.crt"
cp "${OUT}/postgres-client-client.key" "${OUT}/postgres-client-tls.key"

echo ""
echo "Done. Files in: ${OUT}"
echo "Next: run scripts/apply-k8s-tls-secrets.ps1 after ML/Edge clusters are ACTIVE"
