<h1 align="center">plexus-gitops-helm</h1>

<p align="center">
  <img src="https://img.shields.io/badge/Helm-0F1689?style=for-the-badge&logo=helm&logoColor=white" />
  <img src="https://img.shields.io/badge/Argo_CD-EF7B4D?style=for-the-badge&logo=argo&logoColor=white" />
  <img src="https://img.shields.io/badge/Kubernetes-326CE5?style=for-the-badge&logo=kubernetes&logoColor=white" />
  <img src="https://img.shields.io/badge/GKE-4285F4?style=for-the-badge&logo=googlecloud&logoColor=white" />
</p>

<p align="center">
  <em>The desired state of the Plexus cluster. Argo CD reconciles the cluster to
  match this repo — nothing is deployed by hand.</em>
</p>

---

## What this repo is

The single source of truth for what runs in the cluster. Change the cluster by
opening a PR here, not by running `kubectl` or `helm install`.

```
plexus-gitops-helm/
├── charts/plexus/            the chart — all six workloads
│   ├── Chart.yaml
│   ├── values.yaml           ← per-service image tags live here; CI edits these
│   └── templates/
└── argocd/application.yaml   the Application that points Argo CD at charts/plexus
```

Deliberately **separate from the service repos**. A CI job that bumps an image
tag commits *here*, so it cannot retrigger the build that produced it — an
infinite loop that is easy to create when the chart lives beside the code.

## What it deploys

| Workload | Kind | Replicas | Notes |
|---|---|---|---|
| `postgres` | StatefulSet | 1 | `pgvector/pgvector:pg16` + a 10Gi PVC |
| `mcp-host-backend` | Deployment | **1** | agent runtime + MCP client |
| `einvoice-api` | Deployment | **1** | dummy Access Point, in-process SQLite |
| `einvoice-mcp` | Deployment | 1 | the MCP server; safe to scale |
| `frontend` | Deployment | 1 | static React build |
| `gateway` | Deployment | 1 | Caddy; `/api` → host, `/` → frontend |

Two of those replica counts are **pinned at 1 for correctness**, not frugality:

- **`einvoice-api`** stores data in SQLite *inside the process*. Two replicas
  are two divergent databases answering the same clients.
- **`mcp-host-backend`** runs `CREATE TABLE IF NOT EXISTS` on startup and keeps
  the MCP tool cache in memory. Two pods racing that DDL can fail with
  `duplicate key value violates unique constraint "pg_type_typname_nsp_index"`,
  and the second pod would start with a cold cache.

Both also use `strategy: Recreate` so a rollout never briefly runs two.
Raising either needs the schema moved into a migration Job first.

## Secrets

**No secret values are in this repo, and none should ever be.**

`secrets.create` is `false`, so the chart *references* a Secret it does not
create. Make it once per cluster:

```bash
kubectl create namespace plexus
kubectl -n plexus create secret generic plexus-secrets \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --from-literal=OPENAI_API_KEY=sk-... \
  --from-literal=EINVOICE_API_KEY=<shared secret> \
  --from-literal=POSTGRES_PASSWORD=<password>
```

Argo CD will not touch a Secret it did not create, so it survives every sync.

`secrets.create=true` exists for throwaway clusters and refuses to render
without a password, but it can only read values from `values.yaml` — which is in
Git. Use `--set`, never a commit.

The real answer is a secret manager: **Sealed Secrets**, **SOPS**, or
**External Secrets + GCP Secret Manager**. All of them create this same Secret
name, so `secrets.create` stays `false` and nothing else changes.

`EINVOICE_API_KEY` is a *shared* secret — `einvoice-api` compares against it and
`einvoice-mcp` sends it as `X-Api-Key`. One key, both pods, no drift.

## How a change reaches the cluster

```
commit to a service repo
   └─ GitHub Actions builds the image, pushes to Artifact Registry
        └─ opens a PR here bumping that service's `tag:`
             └─ merge to main
                  └─ Argo CD notices, syncs, rolls the Deployment
```

`syncPolicy.automated` has both `selfHeal` and `prune` on: a manual `kubectl
edit` is reverted, and deleting a template deletes the object. That is the point
— the cluster is not somewhere you change things.

## Bootstrapping a cluster

```bash
# 1. cluster (already created; parked at 0 nodes between sessions)
gcloud container clusters resize plexus --num-nodes=2 --zone asia-southeast1-a --quiet
gcloud container clusters get-credentials plexus --zone asia-southeast1-a

# 2. the Secret (see above)

# 3. Argo CD
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl -n argocd rollout status deploy/argocd-server

# 4. hand it this repo — the only kubectl apply you should need
kubectl apply -f argocd/application.yaml
```

### Reaching the UIs

No LoadBalancer and no Ingress by default, so both are port-forwards.

```bash
# the app
kubectl -n plexus port-forward svc/plexus-gateway 8080:80        # → http://localhost:8080

# Argo CD
kubectl -n argocd port-forward svc/argocd-server 8081:443        # → https://localhost:8081
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d                     # admin password
```

`argocd-server` terminates its own TLS, so expect a certificate warning on a
port-forward, or run it with `--insecure` behind a proxy that handles TLS.

## Local checks before pushing

```bash
helm lint charts/plexus
helm template plexus charts/plexus --namespace plexus | less

# what would change in a live cluster
helm diff upgrade plexus charts/plexus -n plexus   # needs the helm-diff plugin
```

## Going public later

`ingress.enabled` is scaffolded and disabled. Turning it on requires
`ingress.host` and refuses to render while `gateway.enabled` is also true, since
the two do the same routing.

> ⚠️ **An ingress controller does not avoid the load-balancer cost.** On GKE,
> `className: gce` provisions an external HTTP(S) LB (~$18–22/month), and
> ingress-nginx installs a `Service` of type `LoadBalancer` by default, which
> also provisions one. To stay at ~$0: ingress-nginx with
> `controller.service.type=NodePort`, or `hostNetwork`, or skip Ingress entirely
> and run `cloudflared` as a pod.

> ⚠️ **The app has no authentication and `allow_origins=["*"]`.** Anyone who
> reaches it can create agents and chat with them, which spends real Anthropic
> and OpenAI credits. Acceptable for a cluster that runs for a few hours at a
> time; not acceptable for anything left up.

## Cost

Nodes are 2× `e2-standard-2` **Spot** in `asia-southeast1-a` — roughly
**$1.45/day** while running, and the control plane is covered by the GKE
free-tier credit.

```bash
gcloud container clusters resize plexus --num-nodes=0 --zone asia-southeast1-a --quiet   # park, ~$0
```

Parked, only the Postgres PVC bills (~$1/month). Argo CD, the Application and
every object definition survive in the control plane, so bringing nodes back
needs no reinstall — the pods simply get scheduled again.
