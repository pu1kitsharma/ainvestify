# V9 initial-preparation result

The final implementation produced all nine sections for three companies with three local model calls each and no retries. Original generation reports are unchanged; separate audits bind their hashes.

| Company and input | Seconds | Sections | Calls |
| --- | ---: | ---: | ---: |
| [Paasa: actual API job](live-paasa.md), current application sources | 51.449 | 9/9 | 3 |
| [SunCulture](sunculture_kenya.md), stored collected sources | 43.11 | 9/9 | 3 |
| [Notpla](notpla_uk.md), stored collected sources | 41.56 | 9/9 | 3 |

The [live cache check](live-cache-check.json) returned the completed result in 21.8–94.3 ms with zero new model calls. The existing POST reconciliation increments metadata revision, but does not regenerate content. Original v7 section content remains unchanged in history; `live-paasa-before.json` is the before snapshot.

See [acceptance.json](acceptance.json), [Paasa audit](live-paasa.audit.json), [SunCulture audit](sunculture_kenya.audit.json), [Notpla audit](notpla_uk.audit.json), and the [full implementation/failure record](../v9-workflow-fix.md). `selection.json` is the evaluator's original unpromoted result before separate audits; it has not been overwritten.

Accepted scope: internal initial source-bound research, founder proposal and two linked contribution/activation work packages. The AI selects services/events and writes the proposed work; code quotes source descriptions/opening context and supplies validated economic methods. This does not establish universal accuracy, verified company performance, a full investor memo, previously unseen-case reliability or the architecture's practitioner/MVP gates. Source context still contains navigation noise; agree precise event/eligibility definitions and edit presentation before external use. No message was sent.
