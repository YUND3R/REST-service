# Kubernetes Secrets Example

Before applying kustomize, create secrets in each Kubernetes cluster.
Use real certificates from your PKI, vault, or CI secret store in production.

## ML Cluster

```bash
kubectl create namespace edu-ml --dry-run=client -o yaml | kubectl apply -f -

kubectl -n edu-ml create secret generic postgres-secrets \
  --from-literal=password='<strong-postgres-password>' \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n edu-ml create secret generic postgres-tls \
  --from-file=tls.crt=./certs/postgres/server.crt \
  --from-file=tls.key=./certs/postgres/server.key \
  --from-file=ca.crt=./certs/postgres/ca.crt \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n edu-ml create secret generic postgres-client-tls \
  --from-file=tls.crt=./certs/postgres/client.crt \
  --from-file=tls.key=./certs/postgres/client.key \
  --from-file=ca.crt=./certs/postgres/ca.crt \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n edu-ml create secret generic redis-tls \
  --from-file=tls.crt=./certs/redis/server.crt \
  --from-file=tls.key=./certs/redis/server.key \
  --from-file=ca.crt=./certs/redis/ca.crt \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n edu-ml create secret generic redis-client-tls \
  --from-file=tls.crt=./certs/redis/client.crt \
  --from-file=tls.key=./certs/redis/client.key \
  --from-file=ca.crt=./certs/redis/ca.crt \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n edu-ml create secret generic gateway-secrets \
  --from-literal=database-url='postgresql+asyncpg://ai_mentor:<strong-postgres-password>@postgres:5432/ai_mentor' \
  --dry-run=client -o yaml | kubectl apply -f -
```

## Edge Cluster

```bash
kubectl create namespace edu-ml --dry-run=client -o yaml | kubectl apply -f -

kubectl -n edu-ml create secret generic redis-tls \
  --from-file=ca.crt=./certs/redis/ca.crt \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n edu-ml create secret generic redis-client-tls \
  --from-file=tls.crt=./certs/redis/client.crt \
  --from-file=tls.key=./certs/redis/client.key \
  --from-file=ca.crt=./certs/redis/ca.crt \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n edu-ml create secret generic postgres-client-tls \
  --from-file=tls.crt=./certs/postgres/client.crt \
  --from-file=tls.key=./certs/postgres/client.key \
  --from-file=ca.crt=./certs/postgres/ca.crt \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n edu-ml create secret generic gateway-secrets \
  --from-literal=database-url='postgresql+asyncpg://ai_mentor:<strong-postgres-password>@postgres:5432/ai_mentor' \
  --dry-run=client -o yaml | kubectl apply -f -
```

## Certificate Requirements

- Redis server certificate must be valid for the Redis DNS name used by clients, currently `redis`.
- PostgreSQL server certificate must be valid for the PostgreSQL DNS name used by clients, currently `postgres`.
- Redis requires client certificates signed by `redis-tls/ca.crt`.
- PostgreSQL requires client certificates signed by `postgres-tls/ca.crt`.
- For PostgreSQL `clientcert=verify-full`, the client certificate CN must match the database user, currently `ai_mentor`.
- In production, replace broad private CIDR ranges in `deploy/k8s/manifests/network-policy-data-tier.yaml` with exact Edge gateway/LB CIDRs.
