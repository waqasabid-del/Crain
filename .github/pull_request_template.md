## What changed

<!-- One or two sentences. What does this do? -->

## Why

<!-- Link the spec section this implements, e.g. md/06-infrastructure.md §4.3 -->

Spec:

## How it was tested

<!-- Not "I ran it". Which tests, and what would they catch? -->

## What to watch after deploy

<!-- Metrics, logs, or behaviour that would indicate a problem -->

---

## Blocking checklist — cannot be waived

<!-- md/17-engineering-standards.md §5.1 -->

- [ ] Tests written for new logic, including failure paths
- [ ] CI green
- [ ] No secrets in code; no new security warnings
- [ ] Tenant isolation verified (anything touching data)
- [ ] AI boundary check — feature cannot score, rank, or allocate

## Expected — defer only with a tracked issue

- [ ] Documentation updated where behaviour changed
- [ ] Accessibility audit passes (UI work)
- [ ] Observability — logs and traces on new paths
- [ ] Spec updated if implementation revealed the spec was wrong

## Review

- [ ] **Self-reviewed** against §3.1 (correctness → security → tenant isolation → tests → readability → performance)
- [ ] This touches auth / tenant isolation / customer data and **needs outside review** before merge
