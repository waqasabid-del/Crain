# System Architecture — Roles, Access & Application Surfaces

**Status:** Draft for review
**Depends on:** [05-ux-design-privacy.md](05-ux-design-privacy.md) (trust commitments), [06-infrastructure.md](06-infrastructure.md) (tenant isolation), [08-roles-and-industries.md](08-roles-and-industries.md) (user roles)

**Why this file exists:** Files 01–14 specify what CAIRN _does_. None specify **who administers it, what CAIRN's own staff can see, or what screens actually exist.** A team cannot start building without this — it determines the auth model, the database schema, and roughly a third of the screens.

---

## 1. Three distinct systems

Every multi-tenant B2B SaaS has three application surfaces. Conflating them is a common and expensive early mistake.

| #     | System                    | Users                               | Purpose                                                                      |
| ----- | ------------------------- | ----------------------------------- | ---------------------------------------------------------------------------- |
| **1** | **Customer Application**  | Everyone at a customer company      | The product itself — briefs, records, feed, documentation                    |
| **2** | **Tenant Administration** | Owner / admin at a customer company | Managing _their_ workspace: members, integrations, privacy settings, billing |
| **3** | **Internal Back-Office**  | CAIRN's own staff                   | Support, billing operations, monitoring, incident response                   |

**These are three different codebases-worth of thinking, not three tabs.** System 3 in particular has entirely different security requirements and is where the trust positioning is most at risk (§5).

---

## 2. Role architecture

### 2.1 Two independent role dimensions

The foundational rule from multi-tenant RBAC practice: **roles are evaluated in the context of the organization the user is currently operating in, not the platform as a whole.** A user's permissions depend on which tenant they are in _and_ what role they hold there.

CAIRN therefore has two separate role systems that must never be conflated:

```
PLATFORM ROLES (CAIRN staff)          TENANT ROLES (customer staff)
├─ Support                            ├─ Owner
├─ Engineering                        ├─ Admin
├─ Billing Ops                        ├─ Member
└─ Security / Compliance              └─ Viewer
        │                                     │
        └── governed by §5 ───────────────────┘
             (deliberately restricted)
```

### 2.2 Tenant roles

| Role       | Can do                                                                                                                     | Cannot do                                                 |
| ---------- | -------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| **Owner**  | Everything in Admin, plus billing, plan changes, transferring ownership, deleting the workspace                            | —                                                         |
| **Admin**  | Connect/disconnect integrations, invite and remove members, configure privacy and retention settings, manage projects      | Billing, workspace deletion, ownership transfer           |
| **Member** | Full product access — briefs, feed, own record, documentation. Correct their own record. Opt out of sources for themselves | Change workspace settings, manage other members           |
| **Viewer** | Read briefs and feed. No integration connection of their own                                                               | Any configuration; any correction beyond their own record |

**Deliberately kept to four.** Practitioners warn about **role explosion** — 500 customers with 10 custom roles each produces 5,000 roles nobody can reason about. The guardrail is a **fixed base set of role templates**, with custom roles deferred until an enterprise customer genuinely requires them (Year 2+, per file 08 §B.4.4 on protecting the small buying committee).

### 2.3 The critical constraint from file 05

**No tenant role may violate the symmetry commitment** (file 05 §B.2). Specifically:

- An Owner or Admin **cannot** see more about an individual member than that member sees about themselves.
- There is no "manager view" showing individual comparison, in any role.
- Admin controls govern _configuration_, never _surveillance depth_.

**This is unusual and worth stating explicitly to engineers**, because the conventional SaaS assumption — that admins see more — is exactly what CAIRN forbids. Admin power here is over settings, not over people.

### 2.4 Permission model

Principles from multi-tenant RBAC practice, applied:

- **No cross-tenant reads or writes**, ever — enforced at the data layer via RLS (file 06 §4.2), not in application code alone.
- **Role assignments are tenant-scoped.** A person who is Owner at Company A and Member at Company B (e.g., a contractor) carries different permissions in each context.
- **Permission evaluation is predictable and debuggable** — a support engineer must be able to answer "why can this person see this?" without reading code.
- **Self-service** — tenant admins manage members and roles without contacting CAIRN.

---

## 3. Authentication architecture

| Concern             | Approach                                                                                                                                                                       |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Sign-in methods** | Email magic link, Google SSO, GitHub SSO. GitHub SSO is natural given the primary integration                                                                                  |
| **Enterprise SSO**  | SAML/OIDC on Business tier (deferred — file 13 Phase 3)                                                                                                                        |
| **Multi-workspace** | One identity may belong to multiple tenants with different roles; workspace switcher required from day one, since contractors and agency staff are common in the target market |
| **Invitations**     | Admin invites by email; invited user joins the existing tenant rather than creating a new one — a common and confusing failure mode if unhandled                               |
| **Session**         | Tenant context bound to session; every request carries resolved tenant + role (file 06 §4.2)                                                                                   |
| **MFA**             | Available to all; enforceable by tenant admins on Business tier                                                                                                                |

---

## 4. Screen inventory

The concrete build list. Approximately 40 screens for v1.

### 4.1 Customer application (~16 screens)

**Onboarding (file 11)**

1. Sign up / sign in
2. Create workspace
3. Connect GitHub — repository selection
4. Connecting / backfill progress _(never an empty state)_
5. First personal summary
6. **Worker notification landing — own record first** _(file 11 §4.1 — highest-leverage screen in the product)_

**Core product** 7. Founder Brief — daily narrative 8. Brief archive / history 9. My Week — personal record 10. Correction interface _(one tap, per file 05 §A.3)_ 11. Team Feed — searchable, filterable 12. Person detail view _(subject to §2.3 symmetry)_ 13. Project / initiative view 14. Search & ask — "what happened with X?" 15. Documentation view — generated docs and their status 16. Notification preferences

### 4.2 Tenant administration (~12 screens)

17. Workspace overview
18. Members list — invite, role assignment, removal
19. Integrations — connect/disconnect per source
20. Integration detail — repository/channel selection, per-source scope
21. **Privacy & data settings** — retention, chat handling, source configuration
22. **Trust & Privacy Center** _(file 05 §B.6 — customer-facing, not admin-only)_
23. Worker notification status — who has been notified, who has opted out
24. Projects configuration
25. Billing overview _(Owner only)_
26. Plan & usage
27. Audit log — tenant's own activity record
28. Data export & deletion _(GDPR Articles 15 and 17)_

### 4.3 Internal back-office (~12 screens)

29. Tenant list & search
30. Tenant detail — plan, usage, health, integration status
31. **Subscription inspector** — billing state without touching Stripe directly
32. Billing actions — credits, refunds, plan changes
33. **Support session request & approval flow** _(§5)_
34. **Internal audit log** — every staff action, tamper-evident _(§5.3)_
35. Pipeline health — ingestion lag, queue depth, error rates
36. **AI cost dashboard** — per feature/tenant/model _(file 09 §7.3)_
37. **Evaluation dashboard** — groundedness, correction rate, boundary violations _(file 10 §4)_
38. Production sampling review queue _(file 10 §4 — the 1% human review)_
39. Feature flags & rollout control
40. Incident / status management

---

## 5. Support access — the sharpest tension in this file

### 5.1 The conflict, stated plainly

Standard SaaS practice is unambiguous: **support teams without impersonation spend 5–10× longer per ticket.** Being able to see what a user sees reduces diagnosis from thirty minutes of back-and-forth to two.

**But CAIRN sells the promise that nobody is watching people's work.** Conventional impersonation — a CAIRN employee silently viewing a customer's activity data — is precisely the thing the product promises not to be. A single leaked incident would be existential in a way it would not be for a generic SaaS tool.

**This cannot be resolved by policy alone. It needs an architectural answer.**

### 5.2 CAIRN's model — consent-gated, time-boxed, customer-visible

| Control                             | Rule                                                                                                                                                                                                                                                               |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Customer-initiated by default**   | Support access is _requested_ by CAIRN staff and _approved_ by a tenant Owner or Admin — not granted by staff to themselves                                                                                                                                        |
| **Time-boxed**                      | Sessions expire automatically (default 60 minutes). No standing access                                                                                                                                                                                             |
| **Scope-limited**                   | Support sessions default to **configuration and diagnostic data**, not activity content. Viewing actual work content requires separate, explicit escalation and approval                                                                                           |
| **Visible to the customer, always** | Every support session appears in the tenant's **own** audit log (screen 27) and in the Trust & Privacy Center — _"CAIRN support accessed configuration on 12 Aug, approved by you, for 40 minutes, reason: integration failure"_                                   |
| **Break-glass exists but is loud**  | Genuine emergencies (data corruption, security incident) permit access without prior approval — but trigger immediate customer notification, security team review, and a permanent record                                                                          |
| **Tamper-evident logging**          | Impersonation logs are **write-only and stored separately from the application database**, per audit-trail practice. When a customer asks whether staff viewed their data, the log must be capable of exonerating — which requires it be beyond staff modification |

### 5.3 Why this becomes an asset rather than a cost

The same move as file 05 §B.3.4: a constraint converted into a differentiator.

**Every competitor's support team can silently view customer data.** CAIRN's cannot — and the customer can verify that themselves, in the product, at any time. _"You can see every time we looked, why, and who approved it"_ is a claim almost no SaaS vendor can make, and it is precisely the kind of proof that makes the trust positioning credible rather than aspirational.

**Accepted cost:** support diagnosis is slower than the industry norm. Mitigated through richer diagnostic tooling that exposes _system state_ without exposing _work content_ — error logs, integration status, pipeline health, and event counts are almost always sufficient to diagnose a problem without reading anyone's actual activity.

---

## 6. Internal staff roles

| Role                      | Access                                                                                      |
| ------------------------- | ------------------------------------------------------------------------------------------- |
| **Support**               | Tenant list, health, subscription inspector, request support sessions                       |
| **Billing Ops**           | Subscription and billing actions. No product data access                                    |
| **Engineering**           | Pipeline health, cost and evaluation dashboards, feature flags. Break-glass with escalation |
| **Security / Compliance** | Full internal audit log, break-glass review, incident management                            |

**Principle: least privilege applies internally too.** A billing operations person has no reason to reach customer activity data, and the system should make that structurally impossible rather than merely discouraged.

**Every internal write action is logged** — who accessed which account, who applied a credit, who changed a subscription, who opened a support session, who ran a bulk operation.

---

## 7. What this file adds to the build plan

Approximately **12 back-office screens and 12 tenant-administration screens** that no prior file accounted for. This is meaningful scope — roughly 60% of the total screen count is _not_ the core product experience.

**Sequencing recommendation:**

- **Phase 0–1:** auth, roles, workspace creation, the tenant isolation model. Foundational, expensive to retrofit.
- **Phase 2:** tenant administration screens, alongside team activation (file 11).
- **Phase 2–3:** internal back-office. **The audit log and support-session model ship with the first internal tool, not after** — retrofitting audit logging is both expensive and, given §5, a trust liability.

---

## Decisions requested from founder

1. **Four tenant roles only (§2.2)** — confirm Owner / Admin / Member / Viewer, with custom roles deferred to enterprise demand. _Recommendation: confirm_ — role explosion is a documented and expensive trap.
2. **Admins see settings, not people (§2.3)** — confirm that no tenant role grants deeper visibility into an individual than that individual has. This contradicts conventional SaaS admin design and must be explicit to engineers.
3. **Support access model (§5.2) — the significant one.** Confirm consent-gated, time-boxed, customer-visible support access, accepting slower support diagnosis in exchange for a verifiable trust claim competitors cannot match.
4. **Break-glass procedure (§5.2)** — confirm emergency access exists but triggers customer notification and security review.
5. **Internal least privilege (§6)** — confirm billing staff cannot reach product data, enforced structurally.
6. **Back-office scope (§7)** — acknowledge roughly 24 screens beyond the core product, and confirm audit logging ships with the first internal tool rather than later.

---

_§5 is the section that matters most here. Every other decision in this file is conventional multi-tenant SaaS architecture; the support-access model is where CAIRN's positioning either holds under operational pressure or quietly fails the first time an engineer needs to debug a customer issue at 2am._
