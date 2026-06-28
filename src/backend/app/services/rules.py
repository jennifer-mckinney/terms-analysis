from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, List, Optional

from ..schemas import Evidence, Finding, Jurisdiction, Severity


@dataclass(frozen=True)
class RulePattern:
    category: str
    severity: Severity
    jurisdictions: List[Jurisdiction]
    explanation: str
    legal_basis: List[str]
    patterns: List[str]
    name: str | None = None


PATTERNS: List[RulePattern] = [
    RulePattern(
        category="Sale/Share",
        severity="High",
        jurisdictions=["US-CA"],
        explanation="Sharing/sale language may trigger CCPA/CPRA opt-out obligations.",
        legal_basis=["CCPA/CPRA opt-out (Sale/Share)"],
        patterns=[
            r"\bsell\b",
            r"\bsale of personal\b",
            r"\bshare\b.*\bpersonal\b",
            r"cross-context behavioral advertising",
        ],
    ),
    RulePattern(
        category="ADM",
        severity="High",
        jurisdictions=["GDPR"],
        explanation="Automated decision-making may require disclosures and safeguards.",
        legal_basis=["GDPR Art. 22"],
        patterns=[
            r"automated decision",
            r"profiling",
            r"algorithmic decision",
            r"solely automated",
        ],
    ),
    RulePattern(
        category="Dark Patterns",
        severity="Medium",
        jurisdictions=["US-CA", "GDPR"],
        explanation="Consent mechanisms that coerce or confuse may be invalid.",
        legal_basis=["GDPR consent validity", "CPRA consent requirements"],
        patterns=[
            r"consent by using",
            r"pre-checked",
            r"cannot opt out",
            r"by continuing to use",
            r"deemed to consent",
        ],
    ),
    RulePattern(
        category="Retention",
        severity="Medium",
        jurisdictions=["US-CA", "GDPR"],
        explanation="Retention periods must be disclosed and limited to necessity.",
        legal_basis=["GDPR Art. 5(1)(e)", "CPRA retention notice"],
        patterns=[
            r"retain",
            r"retention",
            r"as long as necessary",
            r"indefinite",
            r"for so long as",
        ],
    ),
    RulePattern(
        category="User Rights",
        severity="Medium",
        jurisdictions=["US-CA", "GDPR"],
        explanation="Policies must describe access, deletion, and correction rights.",
        legal_basis=["GDPR Art. 15-18", "CCPA/CPRA rights"],
        patterns=[
            r"\bright to (access|request|obtain)\b",
            r"\bright to (delete|erasure|be forgotten)\b",
            r"\bright to (correct|rectif)",
            r"\bopt[- ]?out\b",
            r"\bappeal\b.*\bdecision\b",
            r"\bdata portability\b",
        ],
    ),
    RulePattern(
        category="Minors",
        severity="High",
        jurisdictions=["US-CA", "GDPR"],
        explanation="Children's data requires special protections and disclosures.",
        legal_basis=["GDPR Art. 8", "CPRA minors consent"],
        patterns=[r"children", r"minor", r"under\s?(13|16|18)"],
    ),
    RulePattern(
        category="Sensitive Data",
        severity="High",
        jurisdictions=["US-CA", "GDPR"],
        explanation="Sensitive data handling requires explicit disclosures.",
        legal_basis=["GDPR Art. 9", "CPRA sensitive personal information"],
        patterns=[r"sensitive", r"biometric", r"health data", r"precise geolocation"],
    ),
    RulePattern(
        category="Unilateral Changes",
        severity="Medium",
        jurisdictions=["US-CA", "GDPR"],
        explanation="Unilateral change clauses without notice may be unfair.",
        legal_basis=["Unfair terms notice requirement"],
        patterns=[r"modify these terms", r"change these terms", r"without notice"],
    ),
    RulePattern(
        category="Liability",
        severity="Medium",
        jurisdictions=["US-CA", "GDPR"],
        explanation="Broad liability waivers may limit user remedies.",
        legal_basis=["Consumer protection fairness"],
        patterns=[r"limit(?:ation)? of liability", r"not liable", r"liability limitation"],
    ),
    RulePattern(
        category="UK Data Rights",
        severity="Medium",
        jurisdictions=["UK-GDPR"],
        explanation="UK GDPR requires same rights as EU GDPR; ICO is the supervisory authority.",
        legal_basis=["UK GDPR Art. 13-22", "Data Protection Act 2018"],
        patterns=[
            r"\bICO\b",
            r"\bInformation Commissioner\b",
            r"\bUK GDPR\b",
            r"\bData Protection Act 2018\b",
        ],
    ),
    RulePattern(
        name="UK Data (Use and Access) Act 2025",
        category="UK Data Rights",
        severity="Medium",
        jurisdictions=["UK-GDPR"],
        explanation="UK Data (Use and Access) Act 2025 (enacted Apr 2025) reforms UK GDPR: introduces 'recognised legitimate interests' (no balancing test), smart data portability schemes, and digital verification services. Replaces parts of the retained EU GDPR.",
        legal_basis=["Data (Use and Access) Act 2025 (UK)", "UK GDPR (as amended)", "ICO Guidance on legitimate interests (updated 2025)"],
        patterns=[
            r"\bData.*Use.*Access.*Act\b",
            r"\brecognised legitimate interests?\b",
            r"\bsmart data.*scheme\b",
            r"\bdigital verification service\b",
            r"\bUK.*DUA\b",
            r"\bData.*Use.*Access\b",
        ],
    ),
    RulePattern(
        category="LGPD Rights",
        severity="High",
        jurisdictions=["LGPD"],
        explanation="Brazil LGPD requires lawful basis for processing and grants data subject rights.",
        legal_basis=["LGPD Art. 18", "ANPD guidelines"],
        patterns=[
            r"\bLGPD\b",
            r"\bANPD\b",
            r"\bLei Geral de Prote",
            r"\btitular dos dados\b",
        ],
    ),
    RulePattern(
        category="PIPEDA Consent",
        severity="Medium",
        jurisdictions=["PIPEDA"],
        explanation="PIPEDA requires meaningful consent and limits collection to stated purposes.",
        legal_basis=["PIPEDA Principle 3 (Consent)", "OPC guidelines"],
        patterns=[
            r"\bPIPEDA\b",
            r"\bOPC\b",
            r"\bPrivacy Commissioner of Canada\b",
            r"\bCanadian privacy\b",
        ],
    ),
    RulePattern(
        name="PIPEDA Purpose Limitation",
        category="Purpose Limitation",
        severity="Medium",
        jurisdictions=["PIPEDA"],
        explanation="PIPEDA Principle 4 requires collection limited to identified purposes; Principle 5 limits use to those purposes.",
        legal_basis=[
            "PIPEDA Schedule 1 Principle 4 (Limiting Collection)",
            "PIPEDA Schedule 1 Principle 5 (Limiting Use)",
        ],
        patterns=[
            r"\blimited to.*stated purposes?\b",
            r"\bidentified purposes?\b",
            r"\bcollect.*only.*necessary\b",
            r"\buse.*consistent with.*purpose\b",
            r"\bPIPEDA.*Principle\b",
            r"\bfair information principles?\b",
        ],
    ),
    RulePattern(
        name="PIPEDA Accountability & Breach",
        category="Breach Notification",
        severity="High",
        jurisdictions=["PIPEDA"],
        explanation="PIPEDA requires notification of breaches that pose a real risk of significant harm. Organizations must maintain a breach record.",
        legal_basis=[
            "PIPEDA s. 10.1 (Breach Notification)",
            "PIPEDA s. 10.3 (Record-Keeping)",
        ],
        patterns=[
            r"\breal risk of significant harm\b",
            r"\bsignificant harm\b",
            r"\bPrivacy Commissioner of Canada\b",
            r"\bbreach.*notification.*PIPEDA\b",
            r"\bbreach.*record\b",
            r"\bPIPEDA.*security breach\b",
        ],
    ),
    RulePattern(
        name="Quebec Law 25 / Bill 64",
        category="Privacy Rights",
        severity="High",
        jurisdictions=["CA-QC"],
        explanation="Quebec's Law 25 (in force Sept 2023) requires privacy impact assessments, a named privacy officer, right to de-indexing, and privacy by default.",
        legal_basis=[
            "Quebec Law 25 (Bill 64)",
            "Act respecting the protection of personal information in the private sector",
            "Commission d'accès à l'information (CAI)",
        ],
        patterns=[
            r"\bLaw 25\b",
            r"\bBill 64\b",
            r"\bQuebec.*privacy\b",
            r"\bCommission d'accès à l'information\b",
            r"\bCAI\b",
            r"\bright to de.?index\b",
            r"\bprivacy impact assessment\b",
            r"\bprivacy by default\b",
            r"\bprivacy officer\b",
            r"\bpersonal information protection officer\b",
        ],
    ),
    RulePattern(
        name="GDPR Data Transfers",
        category="Cross-Border Transfer",
        severity="High",
        jurisdictions=["GDPR", "UK-GDPR"],
        explanation="Chapter V of the GDPR restricts personal data transfers to third countries without adequate safeguards (adequacy decision, SCCs, or BCRs).",
        legal_basis=[
            "GDPR Chapter V (Art. 44-49)",
            "UK GDPR Chapter V",
            "Schrems II (C-311/18)",
        ],
        patterns=[
            r"\btransfer.*third countr(?:y|ies)\b",
            r"\badequacy decision\b",
            r"\bstandard contractual clauses?\b",
            r"\bSCCs?\b",
            r"\bbinding corporate rules?\b",
            r"\bBCRs?\b",
            r"\bSchrems\b",
            r"\binternational data transfer\b",
            r"\btransfer.*outside.*(?:EU|EEA|UK)\b",
        ],
    ),
    RulePattern(
        name="ePrivacy / Cookie Consent",
        category="Tracking & Consent",
        severity="Medium",
        jurisdictions=["GDPR"],
        explanation="The ePrivacy Directive (as implemented in EU member states) requires informed prior consent for non-essential cookies and tracking technologies.",
        legal_basis=[
            "ePrivacy Directive 2002/58/EC (Cookie Law)",
            "GDPR Art. 6(1)(a)",
            "CJEU Planet49 (C-673/17)",
        ],
        patterns=[
            r"\bcookie consent\b",
            r"\bcookie policy\b",
            r"\btracking (?:pixels?|technology|cookie)\b",
            r"\bnon.essential cookies?\b",
            r"\bcookies?.*third.party\b",
            r"\banalytics cookies?\b",
            r"\bconsent.*cookies?\b",
            r"\bopt.out.*tracking\b",
        ],
    ),
    RulePattern(
        category="POPIA Processing",
        severity="High",
        jurisdictions=["POPIA"],
        explanation="POPIA requires lawful processing conditions and data subject rights.",
        legal_basis=["POPIA Section 11 (Lawful Processing)", "Information Regulator SA"],
        patterns=[
            r"\bPOPIA\b",
            r"\bInformation Regulator\b",
            r"\bdata subject\b.*\bSouth Africa\b",
            r"\bresponsible party\b",
        ],
    ),
    RulePattern(
        category="DPDP Consent",
        severity="High",
        jurisdictions=["DPDP"],
        explanation="India DPDP Act 2023 requires free, specific, informed consent and data fiduciary obligations.",
        legal_basis=["DPDP Act 2023 Section 6 (Consent)", "Section 8 (Data Fiduciary obligations)"],
        patterns=[
            r"\bDPDP\b",
            r"\bdata fiduciary\b",
            r"\bdata principal\b",
            r"\bDigital Personal Data Protection\b",
        ],
    ),
    RulePattern(
        category="APPI Disclosure",
        severity="Medium",
        jurisdictions=["APPI"],
        explanation="Japan APPI requires disclosure of purpose of use and restrictions on third-party provision.",
        legal_basis=["APPI Art. 17-27 (2022 amendments)", "PPC guidelines"],
        patterns=[
            r"\bAPPI\b",
            r"\bPPC\b",
            r"\bPersonal Information Protection Commission\b",
            r"\b個人情報\b",
        ],
    ),
    RulePattern(
        category="PIPA Processing",
        severity="High",
        jurisdictions=["PIPA"],
        explanation="South Korea PIPA requires consent and restricts cross-border transfers.",
        legal_basis=["PIPA Art. 15 (Lawful bases)", "PIPC guidelines"],
        patterns=[
            r"\bPIPA\b",
            r"\bPIPC\b",
            r"\bPersonal Information Protection Commission\b.*Korea\b",
            r"\b개인정보\b",
        ],
    ),
    RulePattern(
        category="APP Privacy",
        severity="Medium",
        jurisdictions=["APP"],
        explanation="Australian Privacy Principles govern collection, use, and disclosure of personal information.",
        legal_basis=["Privacy Act 1988 (Cth)", "APP 3 (Collection)", "APP 6 (Use and disclosure)"],
        patterns=[
            r"\bAustralian Privacy Principles\b",
            r"\bOAIC\b",
            r"\bPrivacy Act 1988\b",
            r"\bAPP entity\b",
        ],
    ),
    RulePattern(
        name="APP Collection Notice",
        category="Collection Notice",
        severity="Medium",
        jurisdictions=["APP"],
        explanation="APP 3 limits collection to what is reasonably necessary; APP 5 requires notifying individuals of the collection purpose, the APP entity's identity, and how to access the information.",
        legal_basis=[
            "Privacy Act 1988 (Cth) APP 3",
            "Privacy Act 1988 (Cth) APP 5",
            "OAIC APP Guidelines",
        ],
        patterns=[
            r"\bcollection notice\b",
            r"\bpurpose of collection\b",
            r"\bprimary purpose\b",
            r"\bAPP 3\b",
            r"\bAPP 5\b",
            r"\breasonably necessary\b",
            r"\bcollect.*sensitive information\b",
        ],
    ),
    RulePattern(
        name="APP Security & NDB",
        category="Data Security",
        severity="High",
        jurisdictions=["APP"],
        explanation="APP 11 requires reasonable steps to protect personal information from misuse, loss, and unauthorised access. The Notifiable Data Breaches (NDB) scheme requires notification to the OAIC and affected individuals.",
        legal_basis=[
            "Privacy Act 1988 (Cth) APP 11",
            "Privacy Act 1988 (Cth) Part IIIC (NDB scheme)",
            "OAIC",
        ],
        patterns=[
            r"\bNDB scheme\b",
            r"\bnotifiable data breach\b",
            r"\bAPP 11\b",
            r"\breasonable steps.*protect\b",
            r"\bOffice of the Australian Information Commissioner\b",
            r"\bOAIC\b",
            r"\bsecurity safeguards?\b",
            r"\bdata breach.*Australia\b",
        ],
    ),
    RulePattern(
        name="APP Access & Correction",
        category="Individual Rights",
        severity="Medium",
        jurisdictions=["APP"],
        explanation="APP 12 gives individuals the right to access their personal information held by an APP entity. APP 13 requires correction of inaccurate, out-of-date, incomplete, or misleading information.",
        legal_basis=[
            "Privacy Act 1988 (Cth) APP 12",
            "Privacy Act 1988 (Cth) APP 13",
        ],
        patterns=[
            r"\bAPP 12\b",
            r"\bAPP 13\b",
            r"\baccess.*personal information.*Australia\b",
            r"\bAustralian.*right.*access\b",
            r"\bcorrect.*personal information\b",
            r"\binaccurate.*personal information\b",
            r"\brequest.*access.*personal information\b",
        ],
    ),
    RulePattern(
        name="Australian Privacy Tort",
        category="Serious Privacy Invasion",
        severity="High",
        jurisdictions=["APP"],
        explanation="The Privacy and Other Legislation Amendment Act 2024 (Royal Assent Nov 2024) introduces Australia's first statutory tort for serious invasions of privacy (intrusion into seclusion and misuse of private information). Individual claims possible without OAIC involvement.",
        legal_basis=["Privacy and Other Legislation Amendment Act 2024 (POLA)", "Privacy Act 1988 (Cth) Part IIIB (new)", "OAIC"],
        patterns=[
            r"\bserious invasion of privacy\b",
            r"\bintrusion into seclusion\b",
            r"\bmisuse of private information\b",
            r"\bstatutory tort.*privacy\b",
            r"\bPOLA 2024\b",
            r"\bPrivacy.*Legislation Amendment\b",
        ],
    ),
    # ── Africa / Asia ──────────────────────────────────────────
    RulePattern(
        name="Kenya DPA",
        category="Data Rights",
        severity="Medium",
        jurisdictions=["PDPA-KE"],
        explanation="Kenya Data Protection Act 2019 (in force Nov 2019) requires lawful basis, data subject rights (access, correction, erasure), and mandatory breach notification to the Office of the Data Protection Commissioner (ODPC).",
        legal_basis=["Kenya Data Protection Act No. 24 of 2019", "Kenya DPA s. 26 (Data Subject Rights)", "Kenya DPA s. 43 (Breach Notification)", "Office of the Data Protection Commissioner (ODPC)"],
        patterns=[
            r"\bKenya Data Protection Act\b",
            r"\bODPC\b",
            r"\bOffice of the Data Protection Commissioner\b",
            r"\bKenya.*personal data\b",
            r"\bKDPA\b",
            r"\bdata subject.*Kenya\b",
        ],
    ),
    RulePattern(
        name="Thailand PDPA",
        category="Data Rights",
        severity="Medium",
        jurisdictions=["PDPA-TH"],
        explanation="Thailand Personal Data Protection Act B.E. 2562 (fully enforced Jun 1, 2022) requires lawful basis, data subject rights, consent for sensitive data, and 72-hour breach notification to the Personal Data Protection Committee (PDPC).",
        legal_basis=["Thailand PDPA B.E. 2562 (2019)", "Thailand PDPA s. 19 (Lawful Basis)", "Thailand PDPA s. 37 (Rights)", "Thailand PDPA s. 83 (Breach Notification — 72h)", "Personal Data Protection Committee (PDPC)"],
        patterns=[
            r"\bThailand.*PDPA\b",
            r"\bThai.*personal data\b",
            r"\bPDPC\b",
            r"\bPersonal Data Protection Committee\b",
            r"\bThailand.*data subject\b",
            r"\bB\.E\. 2562\b",
        ],
    ),
    RulePattern(
        name="Nigeria NDPA / NDPR",
        category="Data Rights",
        severity="Medium",
        jurisdictions=["NDPR"],
        explanation="Nigeria Data Protection Act 2023 (NDPA, signed Jun 2023) supersedes the 2019 NDPR. Requires lawful basis, data subject rights, mandatory breach notification, and DPO appointment for large-scale processing. Enforced by the Nigeria Data Protection Commission (NDPC).",
        legal_basis=["Nigeria Data Protection Act 2023 (NDPA)", "Nigeria Data Protection Regulation 2019 (NDPR — legacy)", "Nigeria Data Protection Commission (NDPC)", "NDPA s. 34 (Data Subject Rights)", "NDPA s. 40 (Breach Notification)"],
        patterns=[
            r"\bNigeria.*data protection\b",
            r"\bNDPR\b",
            r"\bNDPA\b",
            r"\bNigeria Data Protection Commission\b",
            r"\bNDPC\b",
            r"\bNigeria.*personal data\b",
            r"\bdata subject.*Nigeria\b",
        ],
    ),
    RulePattern(
        category="Privacy as Human Right",
        severity="Medium",
        jurisdictions=["ICCPR-17", "COE-108"],
        explanation="Privacy is a human right under ICCPR Art. 17 (173 state parties) and CoE Convention 108+.",
        legal_basis=["ICCPR Art. 17", "CoE Convention 108+", "UN HRC General Comment 16"],
        patterns=[
            r"\barbitrary interference\b",
            r"\bunlawful interference\b",
            r"\bright to privacy\b",
            r"\bConvention 108\b",
        ],
    ),
    RulePattern(
        category="Children's Privacy",
        severity="High",
        jurisdictions=["US-FED", "US-CA"],
        explanation="COPPA requires verifiable parental consent before collecting personal information from children under 13.",
        legal_basis=["COPPA (15 U.S.C. § 6501)"],
        patterns=[
            r"\bchildren?\s+under\s+13\b|\bchild(?:ren)?'?s?\s+(?:personal\s+)?(?:data|information|privacy)\b|\bverifiable\s+parental\s+consent\b|\bCOPPA\b"
        ],
    ),
    RulePattern(
        category="Health Data",
        severity="High",
        jurisdictions=["US-FED"],
        explanation="HIPAA governs use/disclosure of PHI; a Business Associate Agreement may be required.",
        legal_basis=["HIPAA (45 C.F.R. Parts 160/164)"],
        patterns=[
            r"\b(?:protected\s+health\s+information|PHI|covered\s+entity|business\s+associate|HIPAA)\b"
        ],
    ),
    RulePattern(
        category="Financial Data",
        severity="High",
        jurisdictions=["US-FED"],
        explanation="GLBA restricts sharing of non-public personal financial information by financial institutions.",
        legal_basis=["GLBA (15 U.S.C. § 6801)"],
        patterns=[
            r"\b(?:non.public\s+personal\s+(?:financial\s+)?information|GLBA|Gramm.Leach.Bliley|financial\s+(?:data|information|records))\b"
        ],
    ),
    RulePattern(
        category="Deceptive Practices",
        severity="High",
        jurisdictions=["US-FED"],
        explanation="Broad 'we never share' claims that are contradicted elsewhere in the policy may constitute unfair or deceptive practices under FTC § 5.",
        legal_basis=["FTC Act § 5 (15 U.S.C. § 45)"],
        patterns=[
            r"\b(?:we\s+(?:never|do\s+not|don'?t)\s+(?:sell|share|disclose))\b.{0,120}\b(?:third\s+parties|advertisers|partners)\b"
        ],
    ),
    RulePattern(
        category="Marketing Communications",
        severity="Medium",
        jurisdictions=["US-FED"],
        explanation="CAN-SPAM requires clear opt-out mechanisms for commercial email and prohibits deceptive headers.",
        legal_basis=["CAN-SPAM Act (15 U.S.C. § 7701)"],
        patterns=[
            r"\b(?:commercial\s+email|promotional\s+(?:email|message)|email\s+marketing|unsubscribe|opt.out\s+of\s+(?:email|marketing))\b"
        ],
    ),
    RulePattern(
        category="Biometric Data",
        severity="High",
        jurisdictions=["US-IL", "EU-AI-ACT", "GDPR"],
        explanation="Illinois BIPA requires written consent, retention schedule, and destruction policy before collecting biometric identifiers.",
        legal_basis=[
            "Illinois BIPA (740 ILCS 14)",
            "EU AI Act Art. 5 (real-time biometric surveillance)",
        ],
        patterns=[
            r"\b(?:biometric\s+(?:identifier|data|information)|facial\s+(?:recognition|geometry|scan)|fingerprint|retina\s+scan|voice(?:print)?)\b"
        ],
    ),
    RulePattern(
        category="Sensitive Data / Opt-Out",
        severity="Medium",
        jurisdictions=["US-TX", "US-VA", "US-CO", "US-CT"],
        explanation="Texas TDPSA (eff. July 2024) requires opt-out rights for targeted advertising, sale of personal data, and profiling.",
        legal_basis=["Texas TDPSA (Tex. Bus. & Com. Code § 541)"],
        patterns=[
            r"\b(?:sensitive\s+(?:personal\s+)?(?:data|information)|universal\s+opt.out|data\s+broker|targeted\s+advertising)\b"
        ],
    ),
    RulePattern(
        category="User Rights",
        severity="Medium",
        jurisdictions=["US-VA", "US-CO", "US-CT", "US-TX"],
        explanation="VCDPA and Colorado CPA grant consumers the right to opt out of targeted advertising, sale of personal data, and profiling for significant decisions.",
        legal_basis=[
            "Virginia VCDPA (Va. Code § 59.1-575)",
            "Colorado CPA (C.R.S. § 6-1-1301)",
        ],
        patterns=[
            r"\bright\s+to\s+(?:opt.out|object)\b.{0,80}\b(?:targeted\s+advertising|profiling|sale\s+of\s+(?:personal\s+)?data)\b"
        ],
    ),
    RulePattern(
        name="New Jersey NJDPA Rights",
        category="User Rights",
        severity="Medium",
        jurisdictions=["US-NJ"],
        explanation="New Jersey Data Protection Act (effective Jan 15, 2025) grants consumers opt-out rights from sale of personal data and profiling in furtherance of consequential decisions.",
        legal_basis=["NJ P.L.2023, c.266 (NJDPA) s.7", "NJ NJDPA s.6 (Consumer Rights)"],
        patterns=[
            r"\bNew Jersey.*privacy\b",
            r"\bNJDPA\b",
            r"\bopt.?out.*sale.*New Jersey\b",
            r"\bopt.?out.*profiling.*consequential\b",
            r"\bconsequential decision.*profiling\b",
        ],
    ),
    RulePattern(
        name="Minnesota MCDPA Rights",
        category="User Rights",
        severity="Medium",
        jurisdictions=["US-MN"],
        explanation="Minnesota Consumer Data Privacy Act (effective Jul 31, 2025) grants consumers access, correction, deletion, portability, and opt-out rights. Includes a right to question profiling decisions.",
        legal_basis=["MN HF 4 (MCDPA) s.4 (Consumer Rights)", "MN MCDPA s.5 (Controllers)"],
        patterns=[
            r"\bMinnesota.*privacy\b",
            r"\bMCDPA\b",
            r"\bright to question.*profiling\b",
            r"\bopt.?out.*sale.*Minnesota\b",
        ],
    ),
    RulePattern(
        name="Oregon OCPA Rights",
        category="User Rights",
        severity="Medium",
        jurisdictions=["US-OR"],
        explanation="Oregon Consumer Privacy Act (effective Jul 1, 2024) has the broadest 'consumer' definition of any US state law: covers residents even acting in employment/commercial capacity. Opt-out and access rights apply.",
        legal_basis=["OR SB 619 (OCPA) s.3 (Consumer Rights)", "OR OCPA s.2 (Definitions — broadest consumer scope)"],
        patterns=[
            r"\bOregon.*privacy\b",
            r"\bOCPA\b",
            r"\bopt.?out.*sale.*Oregon\b",
        ],
    ),
    RulePattern(
        category="High-Risk AI",
        severity="High",
        jurisdictions=["EU-AI-ACT"],
        explanation="EU AI Act high-risk AI systems (Annex III sectors: biometrics, critical infrastructure, education, employment, essential services, law enforcement, border control, justice/democracy). GPAI rules in force Aug 2025. High-risk provisions enforceable Aug 2026.",
        legal_basis=[
            "EU AI Act (Regulation 2024/1689) Title III Chapter 2",
            "EU AI Act Annex III (High-Risk Categories)",
            "GPAI Code of Practice (in force Aug 2025)",
            "EU AI Act Art. 6 (Classification rules)",
        ],
        patterns=[
            r"\b(?:high.risk\s+AI|high.risk\s+artificial\s+intelligence|AI\s+system.{0,30}(?:credit|employment|education|law\s+enforcement|border|biometric))\b",
            r"\bhigh.risk AI system\b",
            r"\bAnnex III\b",
            r"\bbiometric categorisation\b",
            r"\bemployment.*AI\b",
            r"\bcritical infrastructure.*AI\b",
            r"\blaw enforcement.*AI\b",
        ],
    ),
    RulePattern(
        name="EU AI Act Prohibited AI",
        category="Prohibited AI",
        severity="Critical",
        jurisdictions=["EU-AI-ACT"],
        explanation="EU AI Act Art. 5 prohibits certain AI practices with no exceptions: real-time biometric surveillance in public spaces, social scoring, manipulation of vulnerable groups, subliminal techniques. In force Aug 1, 2024.",
        legal_basis=["EU AI Act (Regulation 2024/1689) Art. 5 (Prohibited AI Practices)", "In force: Aug 1, 2024"],
        patterns=[
            r"\breal.?time.*biometric.*public\b",
            r"\bsocial scoring\b",
            r"\bsubliminal.*technique\b",
            r"\breal.?time remote biometric identification\b",
            r"\bemotion recognition.*workplace\b",
            r"\bemotion recognition.*education\b",
        ],
    ),
    RulePattern(
        category="Automated Decision-Making",
        severity="High",
        jurisdictions=["EU-AI-ACT", "GDPR", "US-CO"],
        explanation="GDPR Art. 22 and EU AI Act require explicit disclosure and human review rights for fully automated decisions with significant effects.",
        legal_basis=["GDPR Art. 22", "EU AI Act Arts. 13, 86", "Colorado AI Act SB 205"],
        patterns=[
            r"\b(?:automated\s+(?:decision|scoring|profiling|processing)|solely\s+automated|no\s+human\s+(?:review|oversight|involvement))\b"
        ],
    ),
    RulePattern(
        category="AI Training",
        severity="High",
        jurisdictions=["EU-AI-ACT", "US-CA", "OECD-AI"],
        explanation="Using user data to train AI/ML models requires clear disclosure and in many jurisdictions an opt-out right. CPPA AI regulations and EU AI Act both apply.",
        legal_basis=[
            "CPPA AI Regulations (draft 2024)",
            "OECD AI Principle 1.3",
            "EU AI Act Recital 107",
        ],
        patterns=[
            r"\b(?:train(?:ing)?\s+(?:our\s+)?(?:AI|model|algorithm)|use\s+your\s+(?:data|content)\s+to\s+(?:train|improve|develop)|machine\s+learning\s+training)\b"
        ],
    ),
    RulePattern(
        category="AI-Generated Content",
        severity="Medium",
        jurisdictions=["EU-AI-ACT", "US-FED", "UNESCO-AI"],
        explanation="EU AI Act Art. 50 and FTC guidance require disclosure when content is AI-generated, especially for deepfakes and synthetic media.",
        legal_basis=["EU AI Act Art. 50", "FTC AI Guidance (2023)", "UNESCO AI Ethics § 37"],
        patterns=[
            r"\b(?:AI.generated|artificially\s+generated|synthetic\s+(?:media|content|voice|image)|deepfake|generated\s+by\s+(?:AI|an?\s+algorithm))\b"
        ],
    ),
    RulePattern(
        category="GPAI / Generative AI",
        severity="Medium",
        jurisdictions=["EU-AI-ACT", "OECD-AI"],
        explanation="EU AI Act Title VIII imposes transparency and copyright obligations on providers/deployers of general-purpose AI models.",
        legal_basis=["EU AI Act Arts. 51–56 (GPAI)", "OECD AI Principle 1.5"],
        patterns=[
            r"\b(?:general.purpose\s+AI|foundation\s+model|large\s+language\s+model|LLM|GPT|generative\s+AI)\b"
        ],
    ),
    RulePattern(
        category="AI Training Opt-Out",
        severity="Medium",
        jurisdictions=["US-CA", "EU-AI-ACT", "COE-AI-225", "OECD-AI"],
        explanation="CPPA AI regulations and OECD AI Principles require a meaningful opt-out from use of personal data for AI/ML model training.",
        legal_basis=["CPPA AI Regulations (draft)", "OECD AI Principle 1.3b", "CoE CETS 225 Art. 14"],
        patterns=[
            r"\bopt.out\b.{0,80}\b(?:AI\s+training|machine\s+learning|model\s+training|generative\s+AI)\b"
        ],
    ),
    RulePattern(
        category="Algorithmic Accountability",
        severity="Medium",
        jurisdictions=["EU-AI-ACT", "GDPR", "US-CO", "COE-AI-225"],
        explanation="GDPR Art. 22, EU AI Act Art. 86, and Colorado AI Act SB 205 grant rights to explanation and human review of significant algorithmic decisions.",
        legal_basis=["GDPR Art. 22(3)", "EU AI Act Art. 86", "Colorado AI Act SB 205 § 6-1-1703"],
        patterns=[
            r"\b(?:algorithmic\s+(?:transparency|accountability|decision)|right\s+to\s+(?:explanation|contest|human\s+review)|meaningful\s+information.{0,40}logic)\b"
        ],
    ),
    RulePattern(
        category="Consequential AI Decisions",
        severity="High",
        jurisdictions=["US-CO", "EU-AI-ACT"],
        explanation="Colorado AI Act SB 205 (eff. Feb 2026) requires deployers of high-risk AI making consequential decisions to disclose, allow opt-out, and perform impact assessments.",
        legal_basis=["Colorado AI Act SB 205 (C.R.S. § 6-1-1701 et seq.)"],
        patterns=[
            r"\b(?:consequential\s+decisions?|significant\s+(?:decision|effect|impact).{0,60}\b(?:consumer|individual|person)|algorithmic\s+(?:hiring|lending|housing|education|insurance))\b"
        ],
    ),
    RulePattern(
        category="Human Oversight",
        severity="Medium",
        jurisdictions=["COE-AI-225", "OECD-AI", "EU-AI-ACT"],
        explanation="CoE CETS 225 (Art. 14) and OECD AI Principles require meaningful human oversight of AI systems affecting individuals.",
        legal_basis=["CoE CETS 225 Art. 14", "OECD AI Principle 1.4", "EU AI Act Art. 14"],
        patterns=[
            r"\b(?:human\s+(?:oversight|control|supervision).{0,40}\bAI\b|human.in.the.loop|meaningful\s+human\s+(?:control|oversight))\b"
        ],
    ),
    RulePattern(
        category="AI Non-Discrimination",
        severity="High",
        jurisdictions=["UNESCO-AI", "OECD-AI", "EU-AI-ACT"],
        explanation="UNESCO AI Ethics Recommendation (§ 19–20) and OECD AI Principles require AI systems not to discriminate or perpetuate bias.",
        legal_basis=["UNESCO AI Ethics § 19–20", "OECD AI Principle 1.3", "EU AI Act Art. 10"],
        patterns=[
            r"\b(?:algorithmic\s+(?:bias|discrimination|fairness)|AI\s+(?:bias|fairness|discrimination)|discriminat\w+\s+(?:by|through|via)\s+AI)\b"
        ],
    ),
    RulePattern(
        category="Data Security",
        severity="Medium",
        jurisdictions=["US-NY"],
        explanation="NY SHIELD Act (2019) requires reasonable administrative, technical, and physical safeguards for 'private information' of NY residents and broadens the definition of a data breach.",
        legal_basis=["New York SHIELD Act (N.Y. Gen. Bus. Law § 899-bb)"],
        patterns=[
            r"\b(?:private\s+information|SHIELD\s+Act|New\s+York\s+(?:data\s+)?(?:security|breach|privacy)|reasonable\s+(?:administrative|technical|physical)\s+safeguards)\b"
        ],
    ),
    # ── Industry-Specific: HIPAA (Healthcare) ────────────────────
    RulePattern(
        name="HIPAA Business Associate Agreement",
        category="HIPAA Compliance",
        severity="High",
        jurisdictions=["US-FED"],
        explanation="HIPAA requires Business Associate Agreements (BAAs) between covered entities and third parties that process Protected Health Information (PHI).",
        legal_basis=["HIPAA 45 CFR § 164.502(e)", "HIPAA Business Associate Agreement requirements"],
        patterns=[
            r"\b(?:Business Associate Agreement|BAA|covered entity|third.?party.*processing.*PHI)\b",
            r"\b(?:PHI.*third.?party|third.?party.*access.*health\s+(?:data|information))\b",
        ],
    ),
    RulePattern(
        name="HIPAA Minimum Necessary",
        category="HIPAA Compliance",
        severity="High",
        jurisdictions=["US-FED"],
        explanation="HIPAA minimum necessary standard requires organizations to limit access to and use of PHI to the minimum amount needed to accomplish the intended purpose.",
        legal_basis=["HIPAA 45 CFR § 164.502(b)", "HIPAA Minimum Necessary Standard"],
        patterns=[
            r"\b(?:minimum\s+necessary|limited\s+access.*PHI|restricted\s+access.*health\s+data)\b",
            r"\b(?:need.?to.?know.*PHI|access\s+limited.*health\s+information)\b",
        ],
    ),
    RulePattern(
        name="HIPAA PHI Handling",
        category="HIPAA Compliance",
        severity="High",
        jurisdictions=["US-FED"],
        explanation="Policies must explicitly describe how Protected Health Information (PHI) is collected, used, disclosed, and safeguarded.",
        legal_basis=["HIPAA 45 CFR § 164.500–164.534"],
        patterns=[
            r"protected\s+health\s+information",
            r"\bPHI\b",
            r"patient\s+health",
            r"health\s+data",
            r"healthcare\s+data",
            r"patient.*data",
        ],
    ),
    # ── Industry-Specific: PCI DSS (Fintech) ──────────────────────
    RulePattern(
        name="PCI DSS Payment Data",
        category="PCI DSS Compliance",
        severity="High",
        jurisdictions=["US-FED"],
        explanation="PCI DSS requires secure handling of payment card data including cardholder data and sensitive authentication data.",
        legal_basis=["PCI DSS 3.2.1", "PCI DSS Payment Card Industry Data Security Standard"],
        patterns=[
            r"\b(?:cardholder\s+data|payment\s+card|PCI\s+DSS|card\s+(?:number|data)|credit\s+card\s+(?:information|data))\b",
            r"\b(?:sensitive\s+authentication\s+data|CVV|CVC|expiration\s+date.*card)\b",
        ],
    ),
    RulePattern(
        name="PCI DSS Tokenization",
        category="PCI DSS Compliance",
        severity="Medium",
        jurisdictions=["US-FED"],
        explanation="PCI DSS tokenization replaces sensitive payment data with non-sensitive tokens to reduce data security scope.",
        legal_basis=["PCI DSS 3.2.1", "PCI DSS Tokenization guidelines"],
        patterns=[
            r"\b(?:tokenization|tokenized|token.*payment|payment\s+token)\b",
            r"\b(?:reduce.*scope.*PCI|PCI.*out.?of.?scope)\b",
        ],
    ),
    RulePattern(
        name="PCI DSS Payment Processing",
        category="PCI DSS Compliance",
        severity="High",
        jurisdictions=["US-FED"],
        explanation="Organizations processing payment transactions must comply with PCI DSS for secure payment data handling.",
        legal_basis=["PCI DSS Standard 1.0", "Payment Card Industry guidelines"],
        patterns=[
            r"\b(?:payment\s+(?:processing|processor|gateway)|payment\s+data.*secure|transact(?:ion)?.*(?:security|encryption))\b",
            r"\b(?:merchant.*PCI|payment.*compliance|card.*processing)\b",
        ],
    ),
    # ── Industry-Specific: FERPA/COPPA (Education) ─────────────────
    RulePattern(
        name="FERPA Student Records",
        category="FERPA Compliance",
        severity="High",
        jurisdictions=["US-FED"],
        explanation="FERPA protects student education records and requires parental/student consent for disclosure.",
        legal_basis=["FERPA 20 U.S.C. § 1232g", "FERPA Student Privacy Protection"],
        patterns=[
            r"\b(?:FERPA|Family Educational Rights and Privacy Act|student\s+(?:record|data|information).*access)\b",
            r"\b(?:education\s+record.*(?:access|disclosure|parent))\b",
            r"\b(?:student.*privacy.*(?:parent|guardian))\b",
        ],
    ),
    RulePattern(
        name="FERPA Parental Consent",
        category="FERPA Compliance",
        severity="High",
        jurisdictions=["US-FED"],
        explanation="FERPA requires schools to obtain parental/student consent before disclosing education records to third parties.",
        legal_basis=["FERPA 20 U.S.C. § 1232g(b)", "FERPA Disclosure Requirements"],
        patterns=[
            r"parental\s+(?:consent|notification|access)",
            r"prior\s+written\s+consent",
            r"parent.*student\s+record",
            r"parent.*education.*record",
            r"disclose.*student.*record",
            r"third.?party.*access.*student",
        ],
    ),
    RulePattern(
        name="COPPA Children Under 13",
        category="COPPA Compliance",
        severity="Critical",
        jurisdictions=["US-FED"],
        explanation="COPPA (Children's Online Privacy Protection Act) requires verifiable parental consent before collecting any personal information from children under 13.",
        legal_basis=["COPPA 15 U.S.C. § 6501", "COPPA 16 CFR Part 312"],
        patterns=[
            r"\b(?:COPPA|children\s+under\s+13|verifiable\s+parental\s+consent|child.*privacy.*(?:parental|consent))\b",
            r"\b(?:under\s+13\s+years?\b|children.*information.*parental)\b",
            r"\b(?:parental\s+consent.*child|child.*personal\s+information)\b",
        ],
    ),
    RulePattern(
        name="COPPA/FERPA Children's Data",
        category="Children's Privacy",
        severity="High",
        jurisdictions=["US-FED", "US-CA"],
        explanation="Special protections required for children's personal information under COPPA (under 13) and FERPA (education records).",
        legal_basis=["COPPA 15 U.S.C. § 6501", "FERPA 20 U.S.C. § 1232g", "COPPA Parental Notification Rule"],
        patterns=[
            r"\b(?:child(?:ren)?|minor).*(?:information|data|privacy)\b",
            r"\b(?:parental.*(?:consent|notification)|verifiable.*consent.*child)\b",
            r"\b(?:children.*privacy.*protection|protected.*children.*data)\b",
        ],
    ),
]


SEVERITY_BASE = {
    "Low": 0.45,
    "Medium": 0.6,
    "High": 0.75,
    "Critical": 0.9,
}


def _line_number(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _excerpt(text: str, match_start: int, match_end: int, window: int = 140) -> str:
    start = max(0, match_start - window)
    end = min(len(text), match_end + window)
    return text[start:end].strip()


def _extract_sentences(text: str, start_pos: int, end_pos: int, num_sentences: int = 2) -> tuple[str, str]:
    """Extract num_sentences before and after the match position.
    
    Args:
        text: The full text
        start_pos: Start position of the match
        end_pos: End position of the match
        num_sentences: Number of sentences to extract on each side
    
    Returns:
        Tuple of (context_before, context_after)
    """
    import re as regex_module
    
    # Split text into sentences (approximate)
    sentence_pattern = r'[.!?]\s+'
    
    # Find sentences before the match
    before_text = text[:start_pos]
    before_sentences = regex_module.split(sentence_pattern, before_text)
    context_before = ' '.join(before_sentences[-num_sentences:]).strip() if before_sentences else ""
    
    # Find sentences after the match
    after_text = text[end_pos:]
    after_sentences = regex_module.split(sentence_pattern, after_text)
    context_after = ' '.join(after_sentences[:num_sentences]).strip() if after_sentences else ""
    
    return context_before, context_after


def _confidence_rules_based(
    severity: Severity,
    pattern_hits: int,
    match_count: int,
    pattern_total: int,
) -> float:
    """Calculate confidence for rules-based matches (90-95% range).
    
    Rules-based matches are inherently high confidence since they're pattern-matched.
    """
    base = SEVERITY_BASE.get(severity, 0.6)
    hit_ratio = pattern_hits / pattern_total if pattern_total else 0.0
    # For rules-based: return 0.90-0.95 range based on hit quality
    if pattern_hits >= pattern_total * 0.5:  # Multiple patterns hit
        confidence = 0.93 + (0.02 * min(1.0, hit_ratio))  # 0.93-0.95
    else:
        confidence = 0.90 + (0.03 * hit_ratio)  # 0.90-0.93
    return max(0.90, min(0.95, confidence))


def _match_stats(patterns: Iterable[str], text: str) -> tuple[Optional[re.Match], int, int]:
    first_match: Optional[re.Match] = None
    pattern_hits = 0
    match_count = 0
    for pattern in patterns:
        matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
        if matches:
            pattern_hits += 1
            match_count += len(matches)
            if first_match is None:
                first_match = matches[0]
    return first_match, pattern_hits, match_count


def _confidence(
    severity: Severity,
    pattern_hits: int,
    match_count: int,
    pattern_total: int,
) -> float:
    base = SEVERITY_BASE.get(severity, 0.6)
    hit_ratio = pattern_hits / pattern_total if pattern_total else 0.0
    density = min(1.0, match_count / 5)
    score = 0.25 + 0.5 * base + 0.15 * hit_ratio + 0.1 * density
    return max(0.35, min(0.95, score))


def detect_findings(text: str, jurisdictions: List[Jurisdiction]) -> List[Finding]:
    findings: List[Finding] = []
    for rule in PATTERNS:
        if not set(rule.jurisdictions).intersection(jurisdictions):
            continue
        match, pattern_hits, match_count = _match_stats(rule.patterns, text)
        if not match:
            continue
        line_start = _line_number(text, match.start())
        line_end = _line_number(text, match.end())
        excerpt = _excerpt(text, match.start(), match.end())
        
        # Extract context before and after the match
        context_before, context_after = _extract_sentences(text, match.start(), match.end(), num_sentences=2)
        
        # Calculate rules-based confidence (90-95% range)
        confidence = _confidence_rules_based(
            rule.severity,
            pattern_hits=pattern_hits,
            match_count=match_count,
            pattern_total=len(rule.patterns),
        )
        
        # Flag for review if confidence < 0.6
        needs_review = confidence < 0.6
        
        findings.append(
            Finding(
                category=rule.category,
                severity=rule.severity,
                confidence=confidence,
                excerpt=excerpt,
                explanation=rule.explanation,
                jurisdictions=rule.jurisdictions,
                evidence=Evidence(
                    line_start=line_start,
                    line_end=line_end,
                    legal_basis=rule.legal_basis,
                    start_offset=match.start(),
                    end_offset=match.end(),
                    context_before=context_before,
                    context_after=context_after,
                ),
                needs_review=needs_review,
            )
        )
    return findings
