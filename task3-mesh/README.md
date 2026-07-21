# Task 3 — Service Mesh & Zero-Trust (Istio)

## What was built

- Istio installed via `istioctl install` with the **CNI plugin** enabled
  (`istio/istio-operator.yaml`), specifically so the privileged
  `istio-init` container is never needed — the `payments` namespace stays
  compliant with Pod Security Standards `restricted` (Task 1) the whole
  time. This was a required sequencing decision made
  before Task 3 started, and held up in practice.
- `ledger-api` and the `reporting` neighbour are both meshed
  (`istio-injection=enabled` on the namespace); every pod runs with an
  `istio-proxy` sidecar (2/2 containers).
- `PeerAuthentication` STRICT mTLS for the namespace
  (`istio/peerauthentication.yaml`).
- Default-deny `AuthorizationPolicy` (`istio/authorizationpolicy-default-deny.yaml`)
  plus an explicit allow keyed on **workload identity**
  (`spiffe://cluster.local/ns/payments/sa/reporting-sa`, expressed as a
  `principals` match — not an IP) restricted to `GET /health` and
  `GET /transactions` (`istio/authorizationpolicy-allow-reporting.yaml`).
- Kubernetes `NetworkPolicy` default-deny (ingress + egress) for the
  namespace, with explicit allows for DNS, istiod, and the
  `reporting -> ledger-api` and `ingress-nginx -> ledger-api` paths
  (`networkpolicy/*.yaml`).

## Proof

| Claim | Evidence file |
|---|---|
| Plaintext (non-mTLS) request refused under STRICT | `docs/screenshots/task3-mtls-strict-plaintext-refused.txt` — a non-mesh pod hitting the `ledger-api` pod IP directly on :8080 gets `Connection reset by peer` (curl exit 56). |
| Authorized identity allowed, unauthorized identity blocked | `docs/screenshots/task3-authz-allow-deny.txt` — `reporting-sa` gets `HTTP 200`; a second in-mesh pod with no matching `AuthorizationPolicy` rule gets `HTTP 403 RBAC: access denied`. |
| NetworkPolicy is actually enforced (not just declared) | `docs/screenshots/task3-networkpolicy-enforcement.txt` — an unauthorized pod's request times out completely (`HTTP 000`, curl exit 28) *before* it ever reaches Envoy, versus the `403` above which comes *from* Envoy. This is the empirical proof of the two-layer distinction below. |

`istioctl authn tls-check` — referenced in some older Istio docs — was
removed from `istioctl` in this Istio version (1.30). The plaintext-refusal
test above proves the same thing functionally rather than via that
deprecated diagnostic subcommand.

## How workload certificates are issued and rotated

- **Trust root**: `istiod`'s own self-signed root CA, generated at
  install time and stored as the `istio-ca-secret` in `istio-system`
  (a custom/external root can be plugged in via `cacerts` — not done here,
  documented as a production follow-up).
- **Issuance**: each sidecar's Envoy requests a certificate from istiod
  over the **SDS** (Secret Discovery Service) API on first startup,
  presenting its Kubernetes ServiceAccount token as proof of identity.
  istiod validates that token against the API server, then issues an
  X.509 certificate encoding a **SPIFFE** identity URI —
  `spiffe://cluster.local/ns/<namespace>/sa/<service-account>` — as the
  certificate's SAN. This is exactly the identity the `AuthorizationPolicy`
  above matches against; it is cryptographically bound to the workload's
  ServiceAccount, not to an IP or a label a pod could claim for itself.
- **Rotation**: workload certificates default to a 24-hour TTL and are
  automatically rotated by istiod before expiry, transparently to the
  application — no pod restart required.

## Defence-in-depth: what each layer catches that the other doesn't

| Layer | Operates at | Catches | Misses |
|---|---|---|---|
| **Istio mTLS + AuthorizationPolicy** | L7, cryptographic workload identity (SPIFFE/SA) | Spoofed source IPs, lateral movement from a *compromised but meshed* workload using the wrong identity, plaintext/non-mTLS connections, fine-grained method/path abuse | Anything from a pod **without** a sidecar — Istio has no visibility into traffic that never reaches Envoy |
| **Kubernetes NetworkPolicy** | L3/L4, IP/port/namespace | Traffic from an un-meshed or compromised pod that bypasses the sidecar entirely, coarse namespace/egress isolation (this is what actually stops the SSRF sink at `GET /fetch?url=` from reaching arbitrary destinations — see Task 4 finding V1) | Identity — it can't distinguish *which* workload is behind an allowed pod-to-pod path; a compromised `reporting` pod could still reach `ledger-api` at the network layer even if its Istio identity were somehow forged |

Together: NetworkPolicy is the floor (nothing gets a packet through that
isn't on the explicit allow-list, mesh or not), Istio authz is the
identity-aware ceiling on top of it. The evidence above shows this
concretely — the unauthorized network-layer test never reaches Envoy
(`HTTP 000`), while the unauthorized *application*-layer test does reach
Envoy and gets an explicit `403` from it.

## PCI CDE scope note

`ledger-api` handles PANs (`/tokenize`, `/transactions`) and is therefore
in the cardholder data environment (CDE). The mesh boundary here — STRICT
mTLS + identity-scoped `AuthorizationPolicy` + the NetworkPolicy floor —
is what defines the CDE perimeter at the network/service level: only
`reporting-sa` may call `ledger-api`, only on two read-only paths, only
over mutually-authenticated TLS, and only if the underlying L3/L4 path is
separately allow-listed. PCI DSS requires this segmentation to be
*enforced*, not just documented — the rejection evidence above is that
enforcement proof.

## Not implemented (documented as future work)

Bonus items not completed in this pass, prioritised against finishing
Tasks 2 and 4 within the assessment window:
- Istio Ingress Gateway with TLS termination (the gateway itself is
  installed as part of the default Istio profile, but a `Gateway` +
  `VirtualService` exposing `ledger-api` through it with TLS was not
  wired up — Task 1's `ingress-nginx` currently serves that role).
- Canary release via `VirtualService` + `DestinationRule` subset
  weighting.

## Reproduce

```bash
istioctl install -f task3-mesh/istio-operator.yaml -y
kubectl label namespace payments istio-injection=enabled --overwrite
kubectl -n payments rollout restart deployment/ledger-api deployment/reporting

kubectl apply -f task3-mesh/istio/peerauthentication.yaml
kubectl apply -f task3-mesh/istio/authorizationpolicy-default-deny.yaml
kubectl apply -f task3-mesh/istio/authorizationpolicy-allow-reporting.yaml
kubectl apply -f task3-mesh/networkpolicy/
```
