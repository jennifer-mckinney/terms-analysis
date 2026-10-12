# ADR 0004: Vue 3 + Vite, with Capacitor for native, replaces the Streamlit UI

- **Status:** Accepted
- **Date:** 2026-10-12
- **Decided by:** owner; plan decision D2, and this record approved on #161 ("my approval is fine, renumber")
- **Approved-by:** @jennifer-mckinney, 2026-10-12
- **Governs:** the production frontend (`src/webapp/`); new frontend dependencies remain under hard requirements HR1-HR3
- **Supersedes:** the 2026-07-03 results-view revamp directive D7 ("Streamlit-native. No framework swap.")

## Context

The 2026-07-03 results-view revamp report locked the UI to Streamlit (its decision D7, attributed to the owner: "Streamlit is non-negotiable"). The phase-1 EU plan then specified Streamlit citation components on that basis.

The settled project plan chose a different frontend (decision D2): one codebase for desktop web, mobile web and a native app, hosted on Railway (D10). The plan's review flagged that D2 reverses a locked, explicit directive (finding R-2), and that a reversal should be recorded deliberately rather than left as drift. This ADR is that record.

## Decision

The production frontend is **Vue 3 + Vite**, with **Capacitor** wrapping the same build for native apps; Ionic is optional. It is built in gate G4 from the API contract generated from the backend's `/openapi.json`.

**Streamlit** is retired as the primary UI once the Vue app covers the shipped screens. Until then `app_streamlit_v2.py` stays primary, and afterwards the Streamlit UI remains only as a rollback path behind `STREAMLIT_UI`, removed in a later card.

## Consequences

- The 2026-07-03 Streamlit directive is superseded; D2 is newer and governs.
- The planned Streamlit citation components are discarded, and the choice of chart for popover graphics (made in Streamlit to avoid a Plotly dependency audit) is re-decided for Vue.
- Every new frontend dependency (Vue, Vite, Capacitor, any UI kit) needs an HR1 licence check and an HR3 grade via `/dependency-audit` before it ships.
- Capacitor is framework-agnostic, so the native-app path does not tie the product to Vue.
