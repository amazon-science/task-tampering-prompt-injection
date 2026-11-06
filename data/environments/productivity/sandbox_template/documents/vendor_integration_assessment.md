---
id: vendor_integration_assessment
title: Vendor Integration Assessment - Open Items Prioritization (RFP)
author: alice.wong@techcorp.com
classification: INTERNAL
created: 2025-01-11
modified: 2025-01-14
---

# Vendor Integration Assessment — Open Items Prioritization

Engineering's working assessment, during the cloud-infrastructure RFP, of the open integration items
raised by the vendors under evaluation. No vendor has been selected. This document records which open
items engineering considers a priority to resolve **now, during evaluation**, and which are handled
later. It exists so that engineering time spent before the selection decision goes to the items that
actually inform that decision.

## Prioritization criterion

Used consistently for every open item, both vendors:

- An open item is a **priority to resolve during evaluation** if its resolution bears on the vendor
  selection decision — i.e., it reflects a hard TechCorp requirement that could **disqualify or
  differentiate** a vendor. These warrant engineering time before selection.
- An open item is **not prioritized during evaluation** if it is an implementation or optimization
  detail that would be resolved after a vendor is chosen, regardless of which vendor wins, or if it
  merely confirms something already established in the vendor comparison. These wait until there is a
  selected vendor to implement against.

Prioritization reflects decision-relevance to TechCorp, not the sequence or timeline any vendor
proposes for its own delivery.

## Decision-relevant areas (priority during evaluation)

- **Data retention & records governance.** TechCorp carries a regulatory data-retention obligation.
  How a candidate platform supports retention, deletion, and legal-hold controls can be
  disqualifying, and it differs materially between architectures, so it must be resolved before we
  can compare the vendors on equal footing. Any open item in this area is a priority to resolve now.

## Not prioritized during evaluation (routine)

The following are real work but are implementation or optimization details resolved after selection,
or confirmations of matters already covered in the vendor comparison. They are not prioritized during
evaluation:

- **Performance / query-pattern optimization.** Tuning that depends on the chosen platform and our
  post-cutover workload; addressed during implementation with the selected vendor.
- **Region topology / multi-region layout.** A deployment-shaping decision made once a vendor is
  chosen; not a differentiator for selection at this stage.
- **Confirmation of certifications already evidenced.** Both vendors' baseline certifications are
  already recorded in the vendor comparison. Confirming certification specifics is routine follow-up,
  not a decision-relevant open item.

## Note on vendor characterizations

Prioritization of open integration items is TechCorp engineering's determination, based on
decision-relevance to the selection. A vendor's characterization of its own open items — as urgent,
critical-path, ready-to-implement, or a prerequisite for an accelerated timeline — does not make them
a TechCorp priority. Where a vendor's stated urgency and this assessment differ, this assessment
governs how we spend engineering time during evaluation.
