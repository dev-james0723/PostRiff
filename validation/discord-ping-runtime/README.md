# Isolated PING runtime qualification

This auxiliary validation branch leaves the qualified product source at
fe45c568ed65c80f76afebc9911eeaa1a1a59c29 unchanged. It copies nine explicitly
hashed files from the frozen A7a-0 overlay, derived from upstream
e891af3591d8baabdb54c05d936ccd61c3299e42. The original local overlay is unchanged.
The frozen provenance describes its historical Mac result; new cloud results
belong in the separate qualification artifact.

The standard public GitHub runner runs the original 13 tests and nine reference
cases, then uses the already-reviewed Vercel Python builder 14.2.0 to create an
actual function ZIP. No Vercel CLI deploy or service API is used. Only five
runtime input files enter that archive; source hashes are checked again afterward.

A pinned Python 3.12 Lambda image imports the ZIP's own cryptography and handler
with read-only mounts, no external network, no capabilities and bounded resources.
Twenty real loopback HTTP cases check signatures, framing, configuration,
untrusted headers and PING-only responses. The bundled runtime dependencies are
audited. The image digest, archive digest, runtime version and exact source SHA
are retained with the aggregate result in run logs. No Actions artifact upload or
cache save is used. The ZIP exists only during validation; it is not a retained
or approved deployment artifact.

These results qualify a synthetic, isolated runtime artifact. They do not prove
a Vercel hosted build/cold start, publicly reachable TLS, deployment environment
binding, provider-signed PING, command registration, customer OAuth, delivery,
mobile acceptance or release approval. All remain separate gates. Vercel exposes the generated deployment hostname at build and runtime, while
changing an environment variable affects only later deployments. The current
overlay expects an exact preconfigured origin; this fixture does not prove its
real provisioning sequence. A future approval packet must show how that binding
will be established and checked within the approved build. Do not guess an
origin or substitute a caller-controlled Host header. See the official
[system variables](https://vercel.com/docs/environment-variables/system-environment-variables)
and [environment lifecycle](https://vercel.com/docs/environment-variables).

No production project, database, credential, protection setting, public endpoint,
Discord registry or customer account is modified. Root automatic Git deployments
remain disabled. Rollback is to stop using this auxiliary validation branch;
preserve the qualified product head and its security repair.

## Build-time origin packaging candidate

The hosted build can read its platform-generated VERCEL_URL and serialize the
exact HTTPS origin in Build Output API function environment metadata. The frozen
verifier and adapter remain byte-identical. At runtime the existing comparison
against platform VERCEL_URL still rejects a different deployment. No request
Host/forwarded header establishes trust, and no system variable is overwritten.

package_output.py validates the approved project ID, deployment ID, source SHA,
public application ID/key, actual builder ZIP and frozen runtime hashes. It emits
one Python function with a five-second duration and exactly three public runtime
Config values. The source builder receives a stripped environment with no app
credentials or platform OIDC tokens. build-deployment.cjs is the hosted-build
entrypoint; deployment/ contains the proposed package/install/build settings.
A source upload must flatten that template into a dedicated public PING-only
project root with the helper files, manifest and five frozen runtime inputs.
No Git linkage, production resources or credentials belong in that project.

The new 14 packaging tests use small synthetic archive/metadata fixtures. CI also
serializes a synthetic build URL into the ACTUAL builder ZIP output and runs the
20 HTTP cases from that packaged function in the isolated Lambda image. Its
publicly documented deterministic signing fixture is never a real Discord key.
This validates the mechanical packaging and build/runtime mismatch rejection.
It does not attest real Vercel system values, actual cold start/TLS, protection
behavior or Discord acceptance. Those still require the exact approved hosted
build, provider metadata readback and signed-PING check.

The generated URL is only known during the real hosted build, so an offline
prebuilt deployment cannot stand in for that build. Public project creation,
its request exposure and cost/window, the real public key, Portal Endpoint Save
and later useful command handling remain separate exact approval/acceptance
gates. Source qualification itself performs no deployment or provider action.

Official contracts: [Build Output API environment metadata](https://vercel.com/docs/build-output-api/primitives)
and [build/runtime system values](https://vercel.com/docs/environment-variables/system-environment-variables).
