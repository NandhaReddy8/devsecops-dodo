# Task 1 — Deploy & Harden the Workload

## What this deploys

- **ledger-api** — the assignment target service (Flask), forked into
  `apps/ledger-api/`. The vulnerable business logic (`/import` YAML load,
  `/fetch` SSRF, unauthenticated `/transactions`, deterministic `/tokenize`)
  is deliberately left **unremediated at the code level** here — Task 1-3
  harden the *infrastructure* around it; the app-level fixes happen in
  Task 4 after the pentest, so the "before/after" story is complete.
- **reporting** — the neighbour service shipped in the upstream starter
  repo (`curlimages/curl` + `sleep infinity`), used as the authorised
  in-mesh caller for Task 3.

## Hardening applied

| Control | Where |
|---|---|
| Non-root (`runAsUser: 10001`), read-only root FS, all capabilities dropped, seccomp RuntimeDefault | `base/deployment.yaml`, `base/neighbour.yaml` |
| Resource requests/limits + liveness/readiness probes | `base/deployment.yaml` |
| Dedicated least-privilege ServiceAccount, `automountServiceAccountToken: false`, empty Role (no K8s API access needed) | `base/serviceaccount.yaml`, `base/role.yaml` |
| Secrets sealed with Sealed Secrets (Bitnami controller); plaintext never touches git | `secrets/ledger-api-sealedsecret.yaml` |
| Kyverno admission control: disallow-root, disallow-latest-tag, require-signed-images (Audit until Task 2 signs images) | `policies/*.yaml` |
| Pod Security Standards `restricted` enforced at the namespace | `base/namespace.yaml` labels |
| RBAC personas: developer / operator / admin | `policies/rbac-personas.yaml` |

## Why the app image still builds cleanly

The original `requirements.txt` pins Flask 0.12.2 / Werkzeug 0.14.1 /
PyYAML 5.1 (2018-era, dozens of known CVEs — intentionally, so Task 2's
Trivy gate has something real to catch). The **deployed** image
(`apps/ledger-api/requirements.txt`) bumps these to current non-EOL
versions so the container actually runs correctly under `python:3.12-slim`
with the full hardened `securityContext`. The exact original, unmodified
source is preserved at `apps/ledger-api/vulnerable-original/` — it is the
Task 4B pentest target and the "before" baseline for the CVE scan
comparison. Bumping PyYAML to 6.x has a side effect worth noting: the
`/import` endpoint's `yaml.load()` call (no `Loader` arg) now raises
`TypeError` instead of executing arbitrary code — a defence-in-depth
bonus of dependency hygiene, not a substitute for fixing the code.

## Evidence

- `docs/screenshots/task1-pss-rejection-events.txt` — Pod Security Standard
  `restricted` rejecting the original insecure deployment's pods (every
  replica of `ledger-api-977bd4bb7` denied: root, privilege escalation,
  no seccomp profile).
- `docs/screenshots/task1-kyverno-rejection.txt` — same test repeated
  against a differently-named deployment (`ledger-api-insecure-demo`) with
  Kyverno's `disallow-root` / `disallow-latest-tag` policies active
  alongside PSS. Zero insecure pods were ever scheduled; the hardened
  `ledger-api` deployment kept serving traffic throughout with zero
  downtime.

## Sequencing note (resolved)

`require-signed-images` started in **Audit** mode with a placeholder OIDC
subject (a deliberate sequencing choice), by design — flipping to Enforce before a
real signature existed would have blocked every deployment. Task 2's
pipeline has since had a real green run
([run 29757941399](https://github.com/NandhaReddy8/devsecops-dodo/actions/runs/29757941399)),
so the policy now runs in **Enforce** mode with the exact subject/issuer
from that verified `cosign verify` output (see `task2-cicd/README.md`),
not a placeholder. Applying it to the cluster caused zero disruption to
the already-running local deployment, because the policy's
`imageReferences` pattern (`ghcr.io/nandhareddy8/ledger-api*`) only
matches the real GHCR image the pipeline produces — the local
`ledger-api:hardened` image used for the rest of this task's in-cluster
proof is a different reference entirely and isn't subject to signature
verification. Redeploying the actual signed GHCR image into the cluster
(rather than the local build) is listed as follow-up work in the
top-level README.

## Reproduce

```bash
kind create cluster --config infra/kind-config.yaml
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml

# Pin ingress-nginx to the control-plane node — kind's hostPort mapping
# only covers that node, and the upstream manifest's nodeSelector doesn't
# enforce it by itself:
kubectl -n ingress-nginx patch deployment ingress-nginx-controller --type=json \
  -p '[{"op":"add","path":"/spec/template/spec/nodeSelector/ingress-ready","value":"true"}]'

kubectl apply --validate=false -f https://github.com/bitnami-labs/sealed-secrets/releases/latest/download/controller.yaml
helm install kyverno kyverno/kyverno -n kyverno --create-namespace

docker build -t ledger-api:hardened apps/ledger-api/
kind load docker-image ledger-api:hardened --name dodo-devsecops

kubectl apply -k task1-hardening/base
```
