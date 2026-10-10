# FedRAMP 20x Class A Readiness Gap Analysis and Roadmap

**Assessment date:** 2026-10-10  
**Status:** Preliminary repository-based assessment; not an audit, certification,
authorization, or agency determination  
**Target:** FedRAMP 20x Class A as a possible federal-market entry path, subject
to the specific agency use case and current FedRAMP rules

## Executive decision

HarborIQ is **not presently demonstrated ready for FedRAMP Class A**. The
repository contains security engineering and policy artifacts, but describes
the API/application host as not provisioned, records no independent
penetration test, and explicitly says HarborIQ has no SOC 2 report or
attestation. No SOC 2 Type II report was found in the repository. The requested
SOC 2 baseline therefore could not be reviewed or cross-mapped. Obtain and
review the actual report (including scope, period, exceptions, subservice
organizations, and complementary user-entity controls) before treating any
SOC 2 control as an inherited or evidenced control.

This document defines **45 readiness work items**, not 45 official FedRAMP
Class A controls or Key Security Indicators (KSIs). FedRAMP 20x Class A is
outcome-focused and its official reference identifies KSIs and certification
rules; these work items decompose those outcomes into HarborIQ-specific
implementation, evidence, boundary, and market-entry tasks. They are a
prioritized planning backlog, not a claim that every item is a standalone
FedRAMP requirement.

FedRAMP Class A is not synonymous with FIPS 199 Low, Moderate, or High and
does not by itself establish that a specific federal use case is authorized.
Class selection, data sensitivity, agency authorization responsibilities, and
contractual requirements must be confirmed with the prospective agency and
qualified federal compliance counsel. Do not process FCI, CUI, or other
restricted government information in the current commercial deployment absent
explicit authorization and an approved boundary.

## Evidence and assessment limits

This is a repository-document review. No private SOC 2 report, production
account configuration, provider evidence, contracts, SOC reports for
subservice organizations, or independent assessor workpapers were available.
No deployed infrastructure or third-party system was tested.

The following statuses are intentionally distinct:

| Status | Meaning in this assessment |
|---|---|
| **Implemented in repository** | Code or a written procedure exists. This does not establish operational effectiveness. |
| **Tested in repository** | A referenced automated test exists; its latest execution and production applicability have not been independently verified here. |
| **Operational evidence required** | A control depends on deployed settings, recurring activity, retained evidence, or an accountable operator. |
| **Not evidenced / gap** | The reviewed files do not demonstrate the control. Confirm privately before treating it as absent from the organization. |
| **Independent/agency decision** | Requires an assessor, provider, contract, agency, or FedRAMP determination. |

### Repository evidence observed

- `docs/SECURITY_OVERVIEW.md` documents PostgreSQL FORCE RLS, two database
  roles, authentication/session controls, MFA, CI supply-chain scans, and
  control tests. It also states that there is no SOC 2 attestation, MFA is not
  mandatory for owner/admin accounts, operational audit coverage is incomplete,
  and no third-party penetration test has occurred.
- `docs/ARCHITECTURE.md` says the application host is not provisioned and
  describes Render/Neon-oriented commercial architecture. `docs/DEPLOYMENT_RENDER.md`
  documents a pilot stack, not a FedRAMP-authorized environment.
- `docs/INCIDENT_RESPONSE.md` provides a founder-led plan and explicitly treats
  recovery objectives as targets pending a restore drill.
- `docs/KNOWN_LIMITATIONS.md` records no production API/web-app host, missing
  operational observability, incomplete audit events, and no certifications.
- Relevant source tests exist for tenant isolation, authentication, MFA,
  release controls, and security headers. A test file is evidence of a test
  design, not a passing result, operating effectiveness, or assessment.

The repository's own security overview and limitations register should be
rechecked before relying on these observations; their status dates precede
this assessment date.

## Proposed prioritized work items (45)

Priority: **P0** blocks a credible scoping/readiness decision; **P1** required
for the Class A security outcomes or operational evidence; **P2** supporting
assurance, documentation, and federal procurement readiness. “Gap” means no
adequate evidence was established in this review, not a determination that no
private evidence exists.

| # | Priority | Readiness work item | FedRAMP 20x association | Initial repository assessment / exit evidence |
|---:|:---:|---|---|---|
| 1 | P0 | Obtain and review the SOC 2 Type II report; confirm auditor, covered service, control period, opinions, exceptions, carve-outs, and subservice organizations. | Class A entry guidance; crosswalk prerequisite | **Not provided.** Approved report review and exception disposition register. |
| 2 | P0 | Confirm with target agency whether Class A meets the intended use and whether the service processes federal information on the agency's behalf. | Certification class and agency-use rules | **Open.** Written agency/customer determination; no class/impact equivalence assumed. |
| 3 | P0 | Determine data categories and impact: public, commercial confidential, FCI, CUI, PII, and any separately restricted data. | Agency boundary and use-case scoping | **Not evidenced.** Approved categorization and contract-specific handling decision. |
| 4 | P0 | Define the federal cloud service offering (CSO), system boundary, external interfaces, administrative boundary, and all people, services, and components in scope. | Certification Package Overview; agency boundary | **Not evidenced for government use.** Approved boundary diagram and narrative. |
| 5 | P0 | Decide whether to create a segregated government environment; identify isolation from commercial tenants, analytics, support, backups, AI, and CI/CD. | Class A service configuration and agency assurance | Current docs describe a commercial pilot stack, not an approved federal boundary. Architecture decision and tested isolation evidence required. |
| 6 | P1 | Establish a controlled inventory of hardware, software, cloud resources, data stores, identities, interfaces, and owners. | KSI-CNA-RNT; KSI-CMT-LMC | **Not evidenced as a maintained inventory.** Versioned inventory with review cadence. |
| 7 | P1 | Document data flows, trust boundaries, retrieval sources, third-party connections, and authorized data egress. | KSI-CNA-RNT; KSI-SVC-SIN | Tenant design is documented; federal data-flow/boundary review is not. Approved diagrams and flow matrix. |
| 8 | P1 | Identify providers, subcontractors, locations, support access, and inherited controls; obtain provider evidence and contractual commitments. | Certification rules; KSI-SVC-SIN | **Not evidenced for a federal offering.** Approved supplier register and responsibility matrix. |
| 9 | P1 | Create a responsibility matrix assigning control owners, approvers, evidence custodians, and escalation authority. | All KSIs; ongoing certification | Founder-led duties appear in existing incident plan; wider control ownership not evidenced. Signed RACI and named backups. |
| 10 | P1 | Establish a control/evidence register linking each current FedRAMP rule, KSI, implementation, owner, evidence, review date, and exception. | Class A rules and certification package | **Not evidenced.** Version-controlled, source-linked register; record controls as partial until verified. |
| 11 | P1 | Deliver and retain general security training, including completion, overdue follow-up, and effectiveness review. | KSI-CED-RAT | **Not evidenced.** Training content, roster, completion records, and periodic review results. |
| 12 | P1 | Establish role-specific training for privileged/cloud administrators, developers, assessors, and high-risk roles. | KSI-CED-RAT | **Not evidenced.** Role matrix, completion, and refresher records. |
| 13 | P1 | Train engineering staff on secure software delivery, threat modeling, vulnerability response, and protected data handling. | KSI-CED-RAT; KSI-CMT-VTD | Secure coding tests exist; formal training and attendance evidence not found. |
| 14 | P1 | Train incident-response and disaster-recovery personnel; exercise scenarios and review lessons learned. | KSI-CED-RAT; KSI-INR-RIR | Incident plan exists; exercise and effectiveness evidence not established. |
| 15 | P1 | Log and monitor changes to code, configuration, cloud resources, access policy, and service dependencies. | KSI-CMT-LMC | Git/CI and protected-branch controls are documented; production change monitoring/evidence unverified. |
| 16 | P1 | Require attributable change requests, risk/security review, approval, testing, and deployment records for in-scope changes. | KSI-CMT-LMC; KSI-CMT-RVP | PR workflow exists; complete, enforced federal change procedure and samples required. |
| 17 | P1 | Define and maintain approved secure configurations and version-controlled infrastructure/configuration. | KSI-CMT-RMV; KSI-CMT-VTD | Deployment files exist; federal infrastructure and drift handling not established. |
| 18 | P1 | Make production changes through controlled redeployment; restrict or detect direct console/database modifications and emergency changes. | KSI-CMT-RMV; KSI-CMT-LMC | **Not evidenced in a running federal environment.** Enforcement configuration and test evidence. |
| 19 | P1 | Add automated validation for security-relevant changes, including policy/configuration tests and deployment gates. | KSI-CMT-VTD | CI has code and dependency checks; comprehensive infra/security policy tests need review. Retained pipeline evidence. |
| 20 | P1 | Define rollback, emergency change, separation-of-duties, and post-deployment verification procedures. | KSI-CMT-RVP; KSI-CMT-LMC | General operations/rollback documentation exists; government process and records not validated. |
| 21 | P1 | Persistently review change-management effectiveness using incidents, failed changes, unauthorized-change signals, and corrective actions. | KSI-CMT-RVP | **Not evidenced.** Dated management review records, metrics, actions, and closure evidence. |
| 22 | P1 | Maintain release provenance: approved source, build identity, artifact digest, dependency inventory/SBOM, and deployed version. | KSI-CMT-RMV; KSI-CMT-VTD; KSI-CMT-LMC | Dependency audits exist; end-to-end build provenance and deployment traceability not evidenced. |
| 23 | P1 | Define all network zones, ingress/egress paths, trust boundaries, and allowed communications for the federal CSO. | KSI-CNA-RNT | **Not evidenced.** Approved network diagrams, rules, and recurring review. |
| 24 | P1 | Restrict inbound access to required services and management interfaces; verify exposure from the deployed environment. | KSI-CNA-RNT | No production API host is documented; deployed rule evidence unavailable. |
| 25 | P1 | Restrict outbound traffic to documented destinations and business need; monitor exceptions and unexpected egress. | KSI-CNA-RNT | **Not evidenced.** Egress policy, automated tests, exception approvals, and logs. |
| 26 | P1 | Separate development, test, and production identities/data; prevent commercial/federal data mixing. | KSI-CNA-RNT; KSI-SVC-SIN | RLS protects tenants in code; separate federal environment and data segregation not evidenced. |
| 27 | P1 | Continuously review machine-based resources for insecure exposure, drift, and unauthorized changes; assign remediation SLAs. | KSI-CNA-RNT; KSI-CMT-RVP | **Not evidenced operationally.** Scanner/configuration records and closed findings. |
| 28 | P1 | Harden hosts, databases, containers, and orchestration; document approved baselines and deviations. | KSI-CNA-RNT; KSI-SVC-SIN | Docker/deployment hardening exists for commercial app; federal configuration assessment required. |
| 29 | P1 | Define and test network incident alerting, log coverage, and response for prohibited ingress/egress. | KSI-CNA-RNT; KSI-INR-RIR | **Not evidenced.** Alert rules, simulated detection, and response evidence. |
| 30 | P1 | Select identity authority/federation model and document workforce, agency, customer, and service identities separately. | KSI-IAM-AAM; KSI-IAM-APM | Local authentication/RBAC exists; SSO/federation and agency integration not evidenced. |
| 31 | P1 | Require phishing-resistant MFA for privileged and administrative access; define permitted authenticators and recovery. | KSI-IAM-APM | TOTP exists but owner/admin MFA is not mandatory; needs enforcement and tested recovery. |
| 32 | P1 | Automate workforce account, role, group, and service-account provisioning, changes, expiration, and deprovisioning. | KSI-IAM-AAM | Application user lifecycle exists; full privileged/cloud account automation not evidenced. |
| 33 | P1 | Enforce least privilege and role/attribute-based authorization across application, cloud, database, support, and pipeline access. | KSI-IAM-AAM; KSI-IAM-APM | App roles and database privilege boundaries are implemented/tested; cloud/pipeline authorization review required. |
| 34 | P1 | Set joiner/mover/leaver deadlines, immediate termination process, non-human identity owner, and periodic access recertification. | KSI-IAM-AAM | **Not evidenced as an operating control.** Dated account review and deprovisioning records. |
| 35 | P1 | Restrict and log privileged, remote, emergency, and support access; review administrative activity. | KSI-IAM-APM; KSI-IAM-AAM | App audit coverage is incomplete and there is no audit viewer; infrastructure access evidence absent. |
| 36 | P1 | Define device trust or compensating access constraints for workforce and administrator access, based on the agency use case. | KSI-IAM-APM; KSI-IAM-AAM | **Not evidenced.** Approved device/access policy and enforcement records, or documented risk decision. |
| 37 | P1 | Centralize secrets and cryptographic key lifecycle: generation, access, rotation, revocation, backup, and incident response. | KSI-IAM-AAM; KSI-SVC-SIN | Environment-based secrets and MFA encryption are documented; federal KMS/HSM and rotation evidence unavailable. |
| 38 | P1 | Define incident detection, triage, classification, escalation, evidence preservation, and agency/customer notification paths. | KSI-INR-RIR; certification rules | Incident plan exists but is founder-led and describes customer/legal notice generally; contract-specific federal timing is not established. |
| 39 | P1 | Establish and exercise incident playbooks for account compromise, data exposure, cloud compromise, supply chain, and loss of availability. | KSI-INR-RIR | **No exercise evidence found.** Scenarios, results, lessons, and corrective-action closure required. |
| 40 | P1 | Review incident-response procedure effectiveness persistently; track changes resulting from incidents, exercises, and emerging threats. | KSI-INR-RIR | **Not evidenced.** Dated review and effectiveness measures. |
| 41 | P1 | Retain tamper-resistant security and administrative logs with approved access, time synchronization, retention, and export procedures. | KSI-INR-RIR; KSI-CMT-LMC; KSI-SVC-SIN | Structured logs and limited audit rows exist; centralized protected retention and federal access evidence not established. |
| 42 | P1 | Encrypt information in transit and at rest; verify coverage for databases, backups, logs, queues, exports, and administrator connections. | KSI-SVC-SIN | Some encrypted mechanisms are documented; end-to-end deployed evidence unavailable. |
| 43 | P1 | Verify cryptographic algorithm, module validation, key custody, and provider inheritance against actual contract and applicable federal requirements. | KSI-SVC-SIN; agency/provider boundary | **Not evidenced.** Obtain provider/module evidence; do not assume commercial TLS/Fernet satisfies a federal requirement. |
| 44 | P1 | Set data retention, backup, restoration, deletion, and media sanitization rules by information category and contract; perform restore/deletion tests. | KSI-SVC-SIN; KSI-INR-RIR | RPO/RTO are targets pending drills; federal category-specific lifecycle and verified results absent. |
| 45 | P1 | Protect sensitive information from unauthorized use in logs, analytics, support access, AI/model training, demos, or commercial data products. | KSI-SVC-SIN; agency contract and data policy | No approved government data boundary or AI restrictions evidenced. Prohibit use until authorized, then test controls. |

## Remediation roadmap and estimate

The durations below are planning estimates, not FedRAMP or assessor commitments.
They assume named engineering/security ownership, a cooperative provider, no
material SOC 2 exceptions, and agency/customer decisions within the stated
phase. Work can overlap where dependencies permit.

| Phase | Estimate | Work and exit gate |
|---|---:|---|
| 0. Baseline and decision | 2–4 weeks | Complete items 1–5; obtain the private SOC 2 report (if it exists), verify Class A/agency fit, identify data, boundary, and accountable sponsor. **Stop or re-scope** if the report is absent, the target needs a higher assurance class, or the intended data is incompatible with the planned service. |
| 1. Governance and evidence system | 4–8 weeks | Items 6–14 and 38; establish inventories, responsibility matrix, policies, training, control register, and contract-driven data-handling decisions. |
| 2. Isolated platform and identity | 8–16 weeks | Items 5–9, 23–37, 42–45; select/contract for an appropriate hosting and identity stack, isolate the environment, implement access/network/configuration and data protections, gather provider inheritance evidence. Requires architecture and agency review. |
| 3. Operational controls and sustained evidence | 8–16 weeks, then ongoing | Items 11–22 and 27–45; operate training, review, monitoring, incident, change, access, backup, and key-management controls; retain evidence through a representative operating period agreed with the assessor/customer. |
| 4. Independent readiness and package | 4–8 weeks | Reconcile all items against the current official Class A ruleset; remediate findings; assemble the required package and marketplace material; conduct independent readiness assessment and obtain agency/provider decisions. |

**Indicative elapsed range:** approximately **6–12 months** from successful
Phase 0 to a credible independent readiness review, with ongoing assurance
continuing afterward. This estimate is not a promise of certification. If no
SOC 2 Type II report exists, first establish whether one is a prerequisite for
the desired Class A path and plan its audit period with an independent CPA; its
observation period may extend the schedule. Do not treat this roadmap as
replacing or guaranteeing a SOC 2 Type II examination.

### Required policy and artifact updates

Create or revise, approve, assign an owner, and retain version/history for:

1. **System Security/CSO boundary and architecture** — components, data flows,
   trust boundaries, authorized services, users, interfaces, and shared
   responsibility.
2. **Information classification and handling** — federal/commercial separation,
   FCI/CUI decision points, permitted storage/transmission, sharing, AI use,
   support access, retention, deletion, and incident escalation.
3. **Identity, authentication, and access management** — federation, MFA,
   privileged access, provisioning/deprovisioning, service identities,
   access reviews, emergency access, and device/access conditions.
4. **Configuration, change, and release management** — approved baselines,
   source/build provenance, review/approval, automated tests, emergency
   changes, rollback, drift detection, and periodic effectiveness review.
5. **Network and boundary protection** — segmentation, ingress/egress allow
   rules, management interfaces, remote access, monitoring, and exceptions.
6. **Cryptography and key management** — required validated modules where
   applicable, data coverage, key custody, lifecycle, rotation, and provider
   responsibilities.
7. **Logging, audit, and evidence retention** — event scope, protection,
   access, time synchronization, retention, alerting, export, and evidence
   custody.
8. **Incident response and communications** — agency/customer notification
   obligations from the contract, escalation contacts, exercises, evidence,
   and persistent procedure review.
9. **Contingency, backup, restoration, and sanitization** — approved RTO/RPO,
   recovery tests, deletion/media disposition, and category-specific handling.
10. **Secure development, vulnerability, supplier, and training procedures** —
    secure delivery, dependency/SBOM and supplier review, vulnerability
    response, role-based training, and effectiveness measures.

Existing `docs/SECURITY_OVERVIEW.md`, `docs/INCIDENT_RESPONSE.md`,
`docs/DEPLOYMENT.md`, `docs/OPERATIONS_RUNBOOK.md`, and
`docs/KNOWN_LIMITATIONS.md` are useful source material, but need scope-specific
updates and operational evidence; renaming or extending them alone will not
establish control effectiveness.

## Audit-readiness checklist

### Entry and scope

- [ ] Actual SOC 2 Type II report reviewed by authorized personnel; scope,
  opinion, exceptions, period, subservice organizations, and complementary
  user-entity controls recorded. No report is represented as present until
  independently verified.
- [ ] Agency/contract confirms intended use, applicable FedRAMP class, data
  category, impact categorization, and who is responsible for authorization.
- [ ] Current official Class A rules, KSIs, certification package, and
  marketplace rules are version-pinned and checked for changes immediately
  before submission.
- [ ] CSO boundary, diagrams, data flows, inventory, external services,
  suppliers, locations, and shared-responsibility assignments are approved.
- [ ] Federal and commercial environments/data are demonstrably segregated;
  prohibited information flows are tested and documented.

### Control operation and evidence

- [ ] Every applicable rule/KSI has an accountable owner, implementation
  statement, evidence pointer, test/review cadence, exceptions, and remediation
  status.
- [ ] Training, change approvals, automated validation, releases, access
  reviews, account lifecycle, and management reviews have dated samples.
- [ ] Network ingress/egress and administrative access rules are enforced in
  the deployed boundary; monitoring and exception review are evidenced.
- [ ] Encryption, key management, backup, restore, retention, and deletion
  evidence matches contract and provider configuration.
- [ ] Incident exercises, detection, evidence preservation, notification
  procedures, and corrective-action closure have dated records.
- [ ] Vulnerability/dependency handling, SBOM/build provenance, supplier
  reviews, penetration-test findings, and remediation are available to the
  authorized assessor.
- [ ] Evidence is access-controlled, time-stamped, retained, attributable, and
  prepared without exposing customer/government information to unauthorized
  parties.
- [ ] Findings and exceptions are recorded honestly; no open critical security
  defect is hidden by a policy document or control label.

### Independent and agency gates

- [ ] Hosting and identity providers supply current, applicable assurance
  evidence and contractual commitments; inherited controls are confirmed for
  this exact service and boundary.
- [ ] Qualified independent assessor reviews the complete applicable ruleset
  and readiness evidence; remediation is verified.
- [ ] Agency/FedRAMP process, package format, marketplace listing, and
  certification decision are confirmed from the then-current official
  instructions.
- [ ] Legal/procurement review confirms representations, flow-down clauses,
  privacy/records obligations, incident timing, and any FCI/CUI restrictions.
- [ ] Public sales material makes no FedRAMP certification, authorization,
  SOC 2, CMMC, FISMA, or ATO claim absent substantiating evidence and approval.

## Applicable references

Use the rules and agency requirements in force for the actual solicitation and
service boundary. The following official references were consulted for this
preliminary Class A framing; verify their current content before execution:

- [FedRAMP 20x Class A ruleset reference](https://www.fedramp.gov/2026/reference/20x/a/)
- [FedRAMP 20x Class A Key Security Indicators](https://www.fedramp.gov/2026/reference/20x/a/key-security-indicators/)
- [FedRAMP certification classes and agency use](https://www.fedramp.gov/2026/providers/start/class/)
- [FedRAMP certification rules](https://www.fedramp.gov/2026/providers/20x/rules/fedramp-certification/)
- [NIST SP 800-53 Rev. 5](https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final)
- [NIST SP 800-53B control baselines](https://csrc.nist.gov/pubs/sp/800/53/b/upd1/final)
- [FIPS Publication 199](https://csrc.nist.gov/pubs/fips/199/final)
- [FIPS Publication 200](https://csrc.nist.gov/pubs/fips/200/final)

Class A's official outcomes are associated with NIST controls, but this
planning document does not substitute a control-by-control crosswalk for the
current machine-readable ruleset or establish compliance with NIST SP 800-53,
800-171, FISMA, CMMC, or any FedRAMP class.
