# tools/eval - Scope-gate evaluation set

`dataset.jsonl` is a hand-labelled evaluation set for the CHECK B scope gate
(`agent/drafter.py`'s `understand_request()` -> `in_scope`), built to measure
- not assume - that the two-check grounding design (Gate 4-5) actually beats
the single retrieval-distance gate it replaced.

## Schema

Each line: `{query, language, label, rationale, category, case_type, contested, sensitivity_alt_label, id}`

- `language`: `en` / `hi` / `mr`
- `label`: gold answer - `in_scope` or `out_of_scope`
- `category`: which part of the design this case targets - `in_scope`,
  `out_of_scope`, `adversarial` (near-identical vocabulary, opposite labels,
  in pairs), `multilingual`, `ambiguous` (genuinely contested, see below)
- `contested`: true for 20 cases labelled with an honest best call, not a
  clean answer - the original 4 ambiguous cases, plus 16 found on review
  (see "The procedure-disclosure tension" below)
- `sensitivity_alt_label`: for every contested case, the label a defensible
  alternative reading would produce. `null` for uncontested cases.
  `run_eval.py` uses this to score the dataset a second way and report
  both - see "Sensitivity analysis" below.
- `case_type`: see the labelling convention below - this is what makes a
  per-slice accuracy breakdown possible in Gate E2/E3, not just an aggregate

## The labelling convention (read this before trusting the `in_scope` label)

Several in-scope cases are pure grievances with no request in them: *"The
garbage truck stopped coming"*, *"The streetlights have been broken for over
a year."* Strictly read, the user has not asked for a record - they have
complained. The system's correct behaviour is to draft anyway, because the
RTI framing is to request the complaint log, work orders, and budget
allocations behind the service - **but that framing is an inference the
system supplies, not something the user stated.**

So the gold label rests on a convention, made explicit here rather than left
implicit: **a grievance about a public service is labelled `in_scope`,
because a public authority necessarily holds records about that service,
and the Act's purpose is to make those records requestable. The user need
not name a document.**

`case_type` makes this convention auditable instead of hidden inside the
`in_scope` label:

| case_type | label | meaning |
|---|---|---|
| `explicit_request` | in_scope | user names the specific record/document (or specific datum) wanted - no inference needed about *what* to ask for |
| `grievance` | in_scope | user describes a problem, no document named - the system infers the record behind it |
| `advice_seeking` | out_of_scope | wants guidance, a how-to, a recommendation, or generative help (a letter, a poem) |
| `opinion_prediction` | out_of_scope | wants a subjective judgment or a forecast |
| `service_request` | out_of_scope | record-shaped (uses document vocabulary) but fails for a different reason: not a public authority, the record can't exist yet, or it's really a demand for an action/relief/reissuance in records clothing |

This is exactly the slice that matters for comparing the new design against
the old distance-based gate: `grievance` cases are where the old gate
produced false refusals (a citizen's grievance rarely shares vocabulary with
the Act's own procedural text), so reporting accuracy on that slice
separately - not just an aggregate F1 - is the actual comparison Gate E3 is
for.

Two of the four `ambiguous` cases also strain the `case_type` taxonomy, not
just the `label` - flagged in their own `rationale` field rather than forced
to fit silently.

## The procedure-disclosure tension (16 cases, found on review)

Gate E2's first run misclassified two cases identically: *"How can I get
agricultural land mutated in my name after inheritance/after my father's
death?"* - both labelled `advice_seeking`/`out_of_scope`. Two near-identical
failures could mean a classifier weakness, or a wrong gold label, so the
Act's own text was checked before assuming either. Section 4(1)(b) obligates
every public authority to publish "the procedure followed in the decision
making process" (iii), "the rules, regulations, instructions, manuals" it
uses (v), and "the norms set by it for discharge of its functions" (iv) -
confirmed directly against the corpus's own Section 4 chunks. That gives a
real, legally defensible in-scope reading to *any* generic "how do I do X
government procedure" question, not just these two - a citizen could RTI for
the published (or requestable-if-unpublished) procedure/manual itself.

Relabelling only the two failing cases would have been cherry-picking, so
all 16 cases sharing this exact shape (see `PROCEDURE_TENSION_IDS` in the
build history) were marked `contested`, whether the system got them right or
not: `E049, E050, E051, E052, E054, E066, E070, E072, E074, E078, E080, E082,
E090, E092, E094, E096`.

**The gold label was kept as `out_of_scope` (primary), not changed** - the
adversarial-pair design is specifically built to distinguish "the citizen's
own already-filed case" (in scope) from "a generic question anyone could ask
a helpdesk" (out of scope). Almost every government process has *some*
published procedure behind it, so accepting the Section 4 reading universally
would collapse that entire distinction, not sharpen it. `in_scope` is
recorded as the `sensitivity_alt_label` instead, so the tension is visible
and reportable rather than silently resolved either way.

## Sensitivity analysis

`run_eval.py` reports the dataset scored two ways: **PRIMARY** (the `label`
field, as documented above) and **SENSITIVITY** (all 20 contested cases
scored on `sensitivity_alt_label` instead). The result is not what a
score-chasing relabel would predict: flipping all 20 uniformly makes overall
performance *worse* (recall drops from 1.000 to 0.803, false refusal rate
rises from 0.000 to 0.197), because 14 of the 16 procedure-tension cases were
already answered correctly under the PRIMARY convention - only the two land-
mutation cases actually disagree with it. That is itself evidence: the
classifier's real behaviour overwhelmingly matches the practical/conventional
reading this dataset was built around, and the two failures look like a
narrow, specific weakness (something about "land mutation" phrasing) rather
than a systematic pull toward the technical Section 4 reading.

## Leniency check (is the gate just saying yes more often?)

A gate with recall=1.000 and all its errors in one direction (false
positives) could mean genuine precision, or it could mean the gate is simply
biased toward `in_scope` and the zero false-refusal rate is an artefact of
that bias. `run_eval.py` reports each slice's **predicted in_scope rate**
against its **actual base rate** for exactly this reason. On Gate E2's run:
overall predicted-in_scope rate was 0.584 against a 0.531 base rate - a real
but modest +5.3 point lean toward `in_scope`, not a dramatic one. Framed as a
trade, not a clean win: a citizen-facing tool being somewhat lenient toward
drafting when unsure is arguably the right default, but it is a real
property of the design, not free precision, and Gate E3's comparison reports
it for both gates so the difference in leniency is visible rather than
hidden inside the aggregate metrics.

## Sample-size honesty

`run_eval.py` flags any slice with n<20 as **UNDERPOWERED** - a perfect score
at n=10 cannot distinguish 1.00 from 0.90. In this dataset, that currently
applies to `language=hi` (n=10), `language=mr` (n=10), `case_type=opinion_prediction`
(n=10), and `case_type=service_request` (n=10). Treat perfect or near-perfect
scores on these slices as suggestive, not conclusive - they're exactly the
slices most likely to look artificially clean or artificially bad by chance.

## Known limitations of this set

Self-labelled by the same people who built the system being measured, one
annotator, no inter-annotator agreement. See the README's Evaluation section
(added in Gate E4) for the full statement - an eval that overstates its own
authority is worse than no eval.
