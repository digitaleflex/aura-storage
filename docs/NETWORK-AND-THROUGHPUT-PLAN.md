# Network architecture and throughput test plan

**Project:** AURA Storage  
**Status:** design and test procedure only; not deployed or executed  
**Scope:** AURA uploads/downloads, Internet downloads through optional WireGuard, and transfers between PC/iPhone/Android  
**Safety gate:** do not modify the InterServer VPS until SSH access is independently validated and the live host preflight has been reviewed.

## 1. Goals and non-goals

Goals:
- Measure real end-to-end throughput rather than relying on advertised link speed.
- Keep AURA storage traffic and the optional personal VPN independently controllable.
- Prefer direct local transfers when devices share a LAN.
- Record repeatable results before and after any future change.
- Preserve SSH recovery access and avoid exposing internal storage services.

Non-goals:
- A VPN cannot create bandwidth or guarantee faster downloads.
- A single VPS is not high availability.
- No server command in this document has been executed by virtue of being documented.
- Do not use sensitive/private files for performance tests.

## 2. Proposed logical topology

```text
PC / iPhone / Android
  |-- AURA client -- HTTPS/S3 endpoint --> Traefik --> private storage network --> SeaweedFS
  |
  |-- optional WireGuard tunnel --> VPS routing/NAT --> Internet (full-tunnel mode)
  |
  |-- local network transfer ------------------------> peer device (when reachable)
  ```

### AURA path
Use the authenticated HTTPS/S3 endpoint for uploads and downloads. Keep storage internals (SeaweedFS master, volume, filer administration) on a private container network, not publicly exposed. WireGuard is not required for AURA when its HTTPS endpoint is public and properly authenticated; it can instead be used for private-only administration or a private endpoint if the later design explicitly calls for that.

### Personal VPN path
WireGuard is a separate service with separate configuration and one peer/profile per device. Full-tunnel routing is opt-in on the PC, iPhone and Android. Split-tunnel access to private VPS resources can be a separate profile if useful. VPN firewall/NAT rules must be reviewed alongside Docker's rules; do not flush firewall rules or change SSH policy as part of VPN installation.

### Device-to-device path
- Same trusted LAN: test direct local transfer first; this avoids relaying bytes through the VPS.
- Different networks: use a supported encrypted peer-to-peer transfer when available, or relay through a deliberately selected service. Relaying through the VPS adds a network hop and consumes VPS transfer allowance.
- Do not expose temporary file-sharing ports publicly without authentication, encryption and an explicit cleanup plan.

## 3. VPS safety gate (must pass before changes)

1. Confirm the provider console/rescue path is available.
2. Open an SSH session as the intended admin account and keep it open.
3. Open a second independent SSH session using the intended key and verify `sudo -v` and `sudo id -u` (expected `0`).
4. Run the read-only `scripts/host-preflight.sh` and review its output; do not publish secrets or full environment dumps.
5. Confirm running kernel, pending reboot state, OS, disk/filesystem layout, actual provider disk quota, memory, active listeners, routes, firewall manager/rules, and SSH socket/service behavior.
6. Resolve discrepancies and reboot requirement before installing Docker, WireGuard or changing firewall policy.
7. If the second SSH session fails or the recovery path is unavailable, STOP. Do not change SSH, firewall, routing, Docker or VPN.
8. No AURA deployment or original/private-file migration until security, persistence, independent backup and isolated restore checks pass.

These steps are a checklist, not an instruction to execute immediately. The operator has explicitly deferred execution.

## 4. Baseline methodology

Use a private test log with date/time, device, access network, test endpoint/region, file size, direction, VPN state, measured duration, effective throughput, latency/jitter/loss if measured, and notes. Do not log credentials, signed URLs, object names containing personal information, file contents, or private keys.

- Repeat each test at least three times; report median and range, not just the best result.
- Keep device, access network, file size and destination constant when comparing VPN on/off.
- Avoid concurrent downloads, cloud backups and other heavy traffic during controlled tests.
- Test a small non-sensitive random file first, then a larger synthetic file only if the first test is safe.
- Verify integrity with SHA-256 at source and destination.
- Record both the raw result and the exact test command/tool version.
- Distinguish bits/s from bytes/s: 8 bits = 1 byte. A displayed MB/s is not the same as Mbps.
- Never infer public VPS throughput solely from local interface speed or a provider's headline claim.

## 5. Test matrix

### A. Internet baseline (no VPN)
1. From each relevant client/network, run three reputable speed tests and record download, upload and idle latency.
2. Record latency to a stable, non-sensitive public test endpoint; optionally measure jitter and packet loss.
3. Repeat at a second time of day to capture 4G congestion.
4. On the VPS, record CPU, memory, network interface and route before any load test.

### B. VPS path capacity (after safety gate)
1. Install a temporary measurement tool only after approval and change review; prefer a controlled `iperf3` test between the operator's own endpoints.
2. Do not expose an `iperf3` listener to the whole Internet. Restrict source IP/firewall scope and remove the temporary rule/service after the test.
3. Run one direction at a time, short duration first; watch CPU, memory and provider transfer counters.
4. Compare PC-to-VPS and VPS-to-PC results. TCP results depend on RTT, congestion, CPU, MTU and route; one run is not conclusive.
5. Do not saturate the VPS while AURA is serving users or being restored.

### C. AURA upload/download
1. Only after AURA HTTPS, authentication, persistence and storage encryption checks pass, create a synthetic test object (for example 10 MiB, then 100 MiB if appropriate).
2. Upload and download using the same client, endpoint and object size; run three trials each.
3. Measure elapsed time and calculate effective throughput: bytes transferred × 8 / elapsed seconds for bit/s.
4. Compare direct HTTPS/S3 access against a private/VPN path only if both are supported by the design. Keep object, device and access network identical.
5. Verify SHA-256 equality, authenticated access and denial of unauthenticated access. Delete only the synthetic test object after evidence is recorded.
6. Measure small-object performance separately from large-object throughput; latency dominates small files.

### D. Internet downloads with WireGuard
1. Establish baseline without VPN.
2. Once WireGuard is separately approved and deployed, repeat the same downloads through full tunnel, with the same device and access network.
3. Confirm public egress IP, DNS behavior and IPv6 behavior; investigate DNS/IPv6 leaks before using the VPN for sensitive traffic.
4. Compare median throughput, latency, jitter, loss and page-load experience. VPN may improve routing, make no difference, or reduce speed.
5. Check VPS CPU and provider bandwidth/transfer allowance; do not assume the $9/month plan has unlimited egress.

### E. Device-to-device transfers
1. On the same trusted Wi-Fi/LAN, test a supported direct encrypted transfer.
2. On separate networks, test the intended encrypted remote path.
3. Compare direct path with VPS relay only if a relay is intentionally configured; record both legs where possible.
4. Verify file hash and check transfer resumption/retry behavior.
5. Do not treat sending a file through AURA as a direct device-to-device transfer; it measures upload plus download.

## 6. Results template

| Test ID | Scenario | VPN | Device/network | Payload size | Trial 1 | Trial 2 | Trial 3 | Median throughput | Latency/jitter/loss | SHA-256 match | Notes |
|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|
| NET-01 | Internet baseline | Off | | | | | | | | N/A | |
| VPS-01 | Controlled VPS path | N/A | | | | | | | | N/A | |
| AURA-UP-01 | Upload to AURA | Off | | | | | | | | | |
| AURA-DOWN-01 | Download from AURA | Off | | | | | | | | | |
| WEB-VPN-01 | Internet download | On | | | | | | | | N/A | |
| DEVICE-LAN-01 | Device-to-device local | N/A | | | | | | | | | |
| DEVICE-REMOTE-01 | Device-to-device remote | On/relay | | | | | | | | | |

## 7. Decision criteria

- Prefer the path with the best repeatable median and acceptable reliability, not the single highest result.
- For AURA, integrity, authentication, encryption and persistence are release gates regardless of speed.
- For Internet browsing/downloads, enable full-tunnel VPN only if its security/privacy benefit is wanted and measured performance is acceptable.
- For local device transfers, prefer the direct local route when secure and available.
- If VPN competes with AURA for CPU, memory or transfer allowance, reduce concurrent load or separate services; do not compromise AURA security controls to chase throughput.
- If VPS transfer limits, actual disk quota or network limits are unknown, obtain confirmation from the provider before relying on the VPS as a general Internet gateway.

## 8. Rollback and evidence

- Do not start changes until the safety gate is signed off.
- Keep an active SSH session and verified provider recovery console during network changes.
- Before a future WireGuard rollout, capture current firewall/routing configuration in a protected location; never commit secrets.
- Define the exact rollback commands in the change plan after inspecting the actual host. Do not copy generic firewall-flush commands.
- Record all tests in a private log; commit only sanitized summaries.
- Stop immediately on SSH instability, unexpected public listeners, integrity mismatch, storage errors or material degradation to AURA.

## 9. Current state

As of documentation authoring, this is a plan only. No WireGuard, benchmark tool, firewall rule, AURA stack or performance test has been installed or executed by this document. The operator has explicitly requested documentation updates only and will run checks later.
