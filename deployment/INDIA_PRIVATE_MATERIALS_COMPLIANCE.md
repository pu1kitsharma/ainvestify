# India private materials: review and release

Scope confirmed by the user on 10 October 2026: private startup fundraising
documents and internal diligence in India. The product remains worldwide.

## What this implementation establishes

`delivery/compliance.py` checks declared scope, official rule snapshots,
evidence-backed applicability and a qualified human decision against the exact
package. Models may draft and flag questions. They cannot appoint a reviewer,
decide the complete legal ruleset or grant approval.

The private workspace stores `compliance_review` with a scope, matrix and
signoff. The server records qualification separately in
`auth_reviewer_qualifications`; an active compliance membership is also required.
There is no client or model endpoint that grants that authority. Qualification
must cover the jurisdiction, activity and date. No real grant has been created.

The manifest binds the scope/matrix content revision. Signoff binds the manifest,
scope and matrix digests. Changed evidence, scope, files, source version,
freshness or revoked authority invalidates approval. Signoff is excluded from
the content revision to avoid a circular hash dependency. Older manifests omit
the new optional revision and keep their original hashes.

Financial, source, narrative, layout and exported-file checks remain independent
mandatory gates. A passed model review does not qualify a workbook or transaction.

## Rule research register

[`regulatory_sources.json`](regulatory_sources.json) admits official hosts and
records research pointers and byte-retrieval receipts. It is **not** an
applicability matrix. A source hash is recorded only for retained source bytes;
effective dates, qualified verification and approval remain unset.

| Official reference | Retrieval on 10 October 2026 | Review still required |
| --- | --- | --- |
| [Companies Act, India Code](https://www.indiacode.nic.in/bitstream/123456789/2114/5/A2013-18.pdf) | Public web reader returned the Act; local byte download timed out. No source hash. | Current Section 42, complete amendment coverage, issuer/instrument requirements and statutory documents. |
| [Final Rule 14 substitution, G.S.R.752(E), 7 August 2018](https://www.mca.gov.in/Ministry/pdf/RuleProspectusSecurities07_08082018.pdf) | Local TLS failure; web reader inaccessible. No source hash. | Complete current Rule 14 and relevant amendments. The earlier 2017 Act amendment pointer is not Rule 14; the prepublication-style India Code upload was not substituted. |
| [Rule 14 amendment, G.S.R.642(E), 16 October 2020](https://www.mca.gov.in/Ministry/pdf/SecuritiesAmendmentRules_16102020.pdf) | Local TLS failure; web reader returned 403. No source hash. | Amendment chain, current version and actual applicability. Neither historical publication alone establishes the current ruleset. |
| [SEBI IA master circular, 6 February 2026](https://www.sebi.gov.in/sebi_data/attachdocs/feb-2026/1770375291405.pdf) | Retained PDF: 1,351,014 bytes, 99 readable pages. | Actual activity and adviser/analyst applicability; related regulations and later amendments. Do not apply fund disclosure rules automatically to an issuer memo. |
| [RBI foreign investment direction](https://www.rbi.org.in/scripts/FS_Notification.aspx?Id=11200) | Retained HTML: 524,047 bytes; publisher labels it updated through 15 June 2026. | Investor residency, instrument, sector, current amendments and reporting. A publisher update label is not qualified currentness verification. |
| [DPDP Rules 2025, official Gazette](https://www.meity.gov.in/static/uploads/2025/11/53450e6e5dc0bfa85ebd78686cadad39.pdf) | Retained PDF: 2,492,944 bytes, 41 readable pages. | Rule-specific phased commencement, Act commencement and corrigenda. Publication does not make all rules immediately effective. |
| [IRDAI regulations index](https://irdai.gov.in/updated-regulations) | Local byte download timed out. No source hash. | Actual regulated activity, licensing evidence and applicable current sector rules. Marketing descriptions do not establish a licence. |

### Retained bytes and open qualification

The bounded public-only run attempted seven references and retained three source
bodies, totalling **4,368,005 bytes**. Source files and immutable retrieval and
identity-inspection receipts are held locally under
`runtime_qualification/regulatory_sources/2026-10-10/` with file mode `0600`;
that directory is ignored by Git. Earlier DNS-failure receipts were preserved.
Each register entry records the attempted URL, retrieval time, status, local
receipt path and receipt hash. Retained entries also bind the exact source path
and SHA-256. Unavailable sources retain failure receipts without a source hash.

| Retained source | SHA-256 |
| --- | --- |
| SEBI IA circular PDF | `ab1d6f24e184cc2766052b9c3a0fc28ee237b9c2e02fae8d5129f5dd1970cdce` |
| RBI foreign-investment HTML | `660dd0547590d7547193d559879d2d6d8f7176c536818f3af4a8db8bfb1d824a` |
| DPDP rules PDF | `eabc7d05e013144615d78ddc0e8b9c9aac1920e814f4fad38ce6560951f5aa08` |

PDF readability and document identity were checked locally. These checks do not
establish legal completeness, effective applicability, financial qualification
or investor approval. All eight research pointers, including the preserved
historical Act-amendment pointer, remain `unreviewed`; no qualified owner,
verification date, accepted effective date or transaction matrix was supplied.

Generated decks and investment memoranda have no automatic status as statutory
offer/application documents. A qualified owner must identify the required legal
documents, review exclusions and supply the complete matrix for the actual scope.

## Recorded approval path

1. Retain transaction scope evidence, including issuer form, instrument, audience,
   investor residency and regulated activities. Unresolved facts block approval.
2. Retain immutable official source bytes. Bind their SHA-256, version, effective
   period, verification date and reviewer-set freshness deadline.
3. A qualified owner supplies the complete applicability matrix. Every exclusion
   needs evidence; undetermined or incomplete coverage blocks approval.
4. Complete the independent financial/content/file gates for exact artifacts.
5. Record the qualified human's decision against the exact manifest, scope and
   matrix. Publication and downloads recheck trusted membership and qualification.

The frontend's **Check release requirements** records and displays the API's
actual blockers. It neither approves nor releases materials.

### Runtime source and reviewer checks

`compliance-source-evidence-v2` strengthens release assessment without rewriting
saved scope, matrix, manifest or signoff hashes. The server recomputes each
official source body and retrieval receipt hash from its configured archive.
Both must match the exact official URL and the rule/review source hash. Missing,
changed, borrowed or unsafe snapshots block release; an official hostname alone
does not qualify a source.

Scope and rule evidence IDs resolve against the current tenant and room evidence
revision. Private block IDs and `private://document_id/block_id` references require
the actual original inside that tenant/deal upload subtree, no symlink traversal,
and exact retained block/version binding. Rights-indexed public evidence needs
its retained original hash and quote. A database quote alone, an unsupported
alias, an unavailable original or a changed input fails closed. This proves
identity and retention, not the sufficiency or truth of that evidence.

Financial reviewers now require an operator-verified professional authority
record in `auth_reviewer_qualifications`, an active financial membership, an
enabled user, and a grant covering the declared jurisdictions, activity and
current date. Compliance reviewers retain the equivalent legal-review gate.
Financial approvals also need a review date within that professional grant and
no later than the server date. Undated historical approvals fail closed; no
trusted date is inferred from their storage or qualification creation.
There is no HTTP/model appointment or automatic grant. Legacy arbitrary upload
paths and unqualified historical reviewers are preserved as records but cannot
satisfy these stronger release checks.

## Current acceptance

Code integration is implemented. No qualified owner, transaction matrix, real
qualification grant or human signoff has been supplied. Regulatory and investor
approval therefore remain blocked. Official-host admission alone cannot change
that result.
