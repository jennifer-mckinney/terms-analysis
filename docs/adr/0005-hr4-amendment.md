# ADR 0005: HR4 amended for the Railway-hosted UI (document text may transit, never persists)

- **Status:** Accepted
- **Date:** 2026-10-12
- **Decided by:** owner, ruling on #161 ("my approval is fine, renumber"): owner sign-off, no counsel review
- **Approved-by:** @jennifer-mckinney, 2026-10-12
- **Governs:** `.claude/CLAUDE.md` hard requirement HR4 (local-only data, no external API calls), as already scoped to the product by ADR 0001
- **Related:** plan decision D10 (Railway hosts the frontend; railtail bridges to the local backend), D10 consequence 1

## Context

HR4 reads "all data stays local; no external API calls". Under plan decision D10, Railway hosts the frontend, and railtail bridges Railway to the Tailnet and the local backend, LocalAI and corpus. A reviewer pastes a policy into a browser that talks to Railway, which proxies it through railtail to the local backend. The analysed document text therefore transits Railway's infrastructure. That is user-submitted content, so D10 cannot ship under the literal HR4.

The plan's D10 consequence 1 drafted a deliberately narrow amendment and asked for the owner's sign-off (counsel review was optional). On #161 the owner ruled that the owner's approval is sufficient.

## Decision

HR4, amended:

> Analysed document text and analysis results are never persisted outside the local machine. Document text may transit the hosting and tunnel layer (Railway and railtail) in flight, over TLS, solely to reach the local backend. No third-party API is called with document content. No analytics, logging or error-reporting service receives document text.

Everything else in HR4 stands: inference stays local (LocalAI), the legal knowledge base and the SQLite database stay on the local machine, and the product makes no other external call with user data.

## Conditions

The amendment holds only while all of these are true. If any stops being true, HR4 applies in its original wording and the Railway frontend must not receive document text.

1. **Transit only.** The Railway service stores no request body, response body or analysis result: no database, volume, cache or file write of document content.
2. **TLS end to end.** The browser-to-Railway and Railway-to-backend hops are encrypted (HTTPS and the Tailnet).
3. **No body logging.** Railway request logging, and any error tracker added later, never captures request or response bodies. This is verified before a reviewer link is shared.
4. **Authenticated, rate-limited backend.** The backend enforces its API key and rate limit (#133), so a public URL cannot drive the local hardware anonymously.

## Consequences

- D10 can ship once the conditions are met; the owner's machine must be online for the UI to work.
- Any new hosted component that would receive document text needs its own ADR.
- The narrower carve-out for public app-store listings (plan D7) is a separate decision and is not granted by this ADR.
