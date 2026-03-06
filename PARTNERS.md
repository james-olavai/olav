---
version: 0.10.0
author: james@olavai.com
last_updated: 2026-03-06
copyright: Copyright © 2026-2030 DATATECHIE PTY LTD. All rights reserved.
registered_address: Footscray, VIC 3011, Australia
---

# olav Partner Program (OPP)

> **Related Document:** See [LICENSE](LICENSE) for the complete Business Source License (BSL 1.1) terms, including prohibited commercial uses and the Change Date (2030-01-01).

This document outlines the commercial framework for entities seeking to leverage **olav** for third-party service delivery, redistribution, or product integration. By joining the OPP, partners gain the legal rights to commercialize the olav framework while supporting the continued development of professional-grade AIOps.

## 1. Scope of Partnership

The olav Partner Program is mandatory for any commercial entity whose business model involves providing olav-based outputs to third parties. This includes:

* **MSPs & MSSPs:** Utilizing olav agents to manage client infrastructure.
* **CSPs:** Offering managed olav instances or "AIOps-as-a-Service."
* **OEMs & ISVs:** Bundling or embedding olav logic into proprietary hardware or software products.
* **System Integrators (SIs):** Reselling olav as part of a larger digital transformation or automation project.

## 2. Commercial Rights & Benefits

Partners receive a **Commercial Extension** to the BSL 1.1 license, granting the following legal rights:

| Right | Description |
| --- | --- |
| **Commercial Use** | Legal authorization to use olav in revenue-generating services for third-party clients. |
| **Redistribution** | Right to redistribute modified or unmodified versions of the olav core and agents to end-customers. |
| **Modification** | Authorization to create and maintain proprietary forks or specialized agent "Skills" for commercial resale. |
| **OEM & Bundling** | Right to embed olav into hardware appliances, private cloud stacks, or third-party software suites. |
| **White-Labeling** | Option to rebrand the agent interface and reporting modules (available for Strategic Tiers). |

## 3. Partnership Tiers

| Tier | Target Entity | Licensing Model |
| --- | --- | --- |
| **Professional Partner** | Regional MSPs and Boutique SIs | Annual subscription based on managed node count or client volume. |
| **Strategic Partner** | Global CSPs, Large SIs, and OEMs | Revenue-share or enterprise-wide flat-fee licensing. |
| **Development Partner** | Independent Module Developers | Royalty-based model for specialized commercial "Skill" modules. |

## 4. Operational Requirements

To ensure the integrity of the ecosystem and the robustness of the networks managed by olav, Partners agree to:

* **Architectural Documentation:** Maintain documented SOPs (Standard Operating Procedures) for how olav agents are deployed and audited in client environments.
* **Version Compliance:** Ensure that client-facing agents are kept within a maximum of +1 minor version of the official olav core. For example, if official olav is v0.10.x, agents must be v0.10.x or v0.11.x (no drift beyond adjacent minor versions to maintain security and stability).
* **Feedback Loop:** Provide anonymized bug reports and feature requests to the core project to improve the framework's reliability.
* **Security Commitment:** Promptly apply security patches and critical updates within 7 business days of release.

## 5. Vision Alignment

While we have removed mandatory high-level certifications (e.g., CCIE) to ensure program accessibility, the OPP remains committed to **Technical Excellence**.

* We encourage partners to utilize olav to **automate the mundane**, allowing their technical staff to focus on high-value architectural improvements.
* Partners are expected to promote the "Robustness-First" philosophy, ensuring that AI-driven automation enhances network stability rather than just reducing headcount.

## 6. Data Privacy & Security

### Telemetry & Bug Reporting

* **Anonymization:** All bug reports and performance telemetry MUST be scrubbed of customer/network identifiable information (NII) before submission.
* **Data Retention:** DATATECHIE PTY LTD retains all submitted reports for maximum 12 months unless required by law.
* **Access Control:** Submitted data is accessible only to the olav core team and partners with explicit need-to-know.
* **GDPR/Privacy Compliance:** Partners are responsible for ensuring local privacy laws (GDPR, CCPA, etc.) are honored when collecting and submitting data from client environments.
* **Submission Frequency:** Aggregated quarterly reports required (due within 7 days of quarter-end).

---

## 7. Licensing & Legal Framework

### Alignment with LICENSE Terms

The rights granted under this Partner Program constitute a **Commercial Extension to the Business Source License (BSL 1.1)**.

* **Free Grant (no license required):** Internal expert use by direct employees (see LICENSE § A)
* **Partner License (required):** All prohibited commercial uses defined in LICENSE § B require formal partnership
* **Automatic Conversion:** On 2030-01-01, all licenses convert to Apache 2.0. Partners retain perpetual rights under Terms already granted.

### Key Compliance Points

Partners MUST ensure:
* Client-facing agents maintain version parity with official olav core (max 2 minor versions drift)
* Audit trails and SOPs documented for compliance audits
* Anonymized telemetry/bug reports submitted quarterly

## 8. Commercial Pricing

Pricing is determined on a **per-partner basis** and depends on:

* Organization size and annual managed node count
* Partnership tier (Professional, Strategic, Development)
* Deployment model (on-premises, hybrid, SaaS)
* Custom feature development requirements

**To discuss pricing:** Submit an initial inquiry to **james@olavai.com** with your use case and scale. We will provide a custom proposal based on your specific requirements.

---

## 9. Onboarding & Licensing Process

To formalize a partnership and obtain a Commercial License Key:

1. **Application:** Submit your intended use case and estimated scale to **james@olavai.com**.
   * Expected information: Organization size, annual managed node count, use case (MSP/CSP/OEM/SI/Dev), target market
2. **Pricing Discussion:** Commercial team will propose tier-specific pricing model based on your requirements (if not already discussed).
3. **Review:** Technical and commercial alignment review (typically 3-5 business days).
   * Architecture review to ensure compliance with § 4 (Operational Requirements)
4. **Execution:** Signing of the Commercial Partner Agreement and issuance of the License Grant (valid 2026-03-06 to 2030-01-01).
5. **Access:** Gain access to the Partner-only repository for advanced integration tools and OEM-ready binaries.
6. **Renewal:** On or after 2030-01-01, all partners operate under Apache License 2.0 (no license renewal required).

---

## 10. Violations & Remediation

### License Violations

Partner licenses may be suspended or revoked if:

* **Version Non-Compliance:** Deployed agents exceed +1 minor version drift from official olav core for more than 30 days
* **Commercial Misuse:** Unauthorized use outside the granted Partnership Tier (e.g., CSP using Professional tier pricing for enterprise scale)
* **Data Privacy Breach:** Failure to anonymize sensitive data in submitted reports or unauthorized third-party redistribution of core code
* **Non-Payment:** Non-payment of license fees for 60+ days beyond due date
* **Compliance Audit Failure:** Refusal to provide SOPs or audit trails when requested

### Remediation Process

1. **Notice:** DATATECHIE PTY LTD notifies partner of the violation with supporting evidence
2. **Response Period:** Partner has 14 business days to respond and propose remediation
3. **Remediation Plan:** If accepted, partner must demonstrate compliance within 30 days
4. **Escalation:** Failure to remediate results in 30-day suspension, then permanent revocation if unresolved
5. **Appeal:** Partners may appeal via formal request to **james@olavai.com** within 7 days of revocation

### Financial Impact

* **Suspension:** License fees are not refunded during suspension period
* **Revocation:** No refund of prepaid fees; partner loses access to Partner-only repository and support