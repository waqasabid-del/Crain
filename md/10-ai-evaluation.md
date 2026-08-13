# AI Evaluation & Quality Assurance

**Status:** ✅ LOCKED — decisions resolved, ready for implementation
**Depends on:** [09-understanding-layer.md](09-understanding-layer.md) (the system under test)
**Governs:** Every change to prompts, models, or pipeline logic

**Why this file exists:** The original product proposal named the evaluation framework "non-negotiable" and warned that without it _"AI quality drifts silently and customer trust erodes."_ That is precisely right, and it is the most commonly skipped investment in AI products. This file specifies what that framework actually is.

**The governing principle**, stated plainly by current practice: build the evaluation harness _before_ scaling the pipeline — because without it, **every quality regression looks identical.** A model change, a prompt tweak, and a data drift all present as "the summaries feel worse," with no way to distinguish them.

---

## 1. What is being evaluated

CAIRN's failure modes are specific, and each needs its own measurement. Generic "summary quality" is not a metric — it is an excuse not to measure.

| Failure mode               | Why it matters                                                             | Metric                                                    |
| -------------------------- | -------------------------------------------------------------------------- | --------------------------------------------------------- |
| **Fabricated claims**      | Worst possible failure — an invented statement about a person's work       | Groundedness: % of claims traceable to cited evidence     |
| **Misattribution**         | Wrong person credited or blamed. Destroys trust irrecoverably (file 01 §5) | Attribution accuracy against labeled ground truth         |
| **Stale facts as current** | "Ali is on auth" three weeks after he moved to billing (file 09 §3.2)      | Temporal correctness on time-sensitive cases              |
| **Overconfidence**         | Asserting a noisy meeting inference as established fact (file 03 §5)       | Calibration: does stated confidence match actual accuracy |
| **Missed signal**          | Real blocker never surfaced — the quiet failure nobody reports             | Recall against labeled must-surface events                |
| **Tone violation**         | Judgmental or evaluative language about a person (file 05 §A.5)            | Automated tone classification, zero-tolerance             |
| **Boundary violation**     | Any output that scores, ranks, or allocates work (file 05 §B.3.3)          | Hard rule check — **any failure is a release blocker**    |

**Note on the last row:** boundary violations are not a quality metric with a threshold. A single occurrence is a regulatory and positioning failure (file 05 §B.3.3), and blocks release outright.

---

## 2. The golden dataset

### 2.1 Composition

The evaluation set is **200–500 curated examples**, matching the industry standard and the original proposal's "200+ scenarios."

**Critically: built from real production failures, not synthetic examples.** Synthetic cases test what we imagined going wrong; real failures test what actually goes wrong. The distinction is decisive in practice.

Bootstrapping before production data exists:

1. Run the pipeline against the CAIRN team's own activity — the product is used internally from month one (dogfooding is both a quality mechanism and a design forcing function).
2. Grade outputs by hand and capture every failure.
3. Recruit design partners early (the original proposal's LOI gate) and treat their corrections as the first real dataset.

Once live, **every human correction becomes an evaluation case** (file 09 §7). This is the compounding advantage: CAIRN's evaluation set is built from its own real failure modes, which no competitor can replicate.

### 2.2 The dataset is production code

Standard practice, adopted here without modification: **version the evaluation dataset, require code review on changes, and treat modifications or deletions of ground truth as production risk.**

A quietly edited ground-truth label can make a regression disappear from the metrics while the product gets worse. Changes to expected outputs require the same review rigor as changes to the pipeline itself.

### 2.3 Coverage requirements

The set must span all four data sources, all five roles (file 08 Part A), the noisy-input cases that make file 03 hard, edge cases (empty weeks, single-person teams, heavy bot activity), and — deliberately — cases where **the correct answer is "not enough information"** (file 09 §6). If nothing in the evaluation set rewards admitting uncertainty, the system will be trained by its own metrics to guess.

---

## 3. LLM-as-judge — calibrated, never trusted blindly

Much of what matters here is subjective: is this summary useful, well-grounded, appropriately hedged? An LLM judge scales this, **but only if calibrated against human judgment.**

### 3.1 Calibration procedure

The established method, adopted directly:

1. Collect **50 real failures**.
2. One domain expert grades them **binary pass/fail with written critiques** — not numeric scores, which are inconsistent between graders.
3. Calibrate the judge prompt against those verdicts.
4. Target **85–90% agreement** with the human reference set.
5. **Re-calibrate whenever the judge model changes.** A judge upgrade is a measurement-system change and invalidates prior baselines.

### 3.2 Harness consistency

Same judge model, same rubric, same temperature across every run. Any variation makes results incomparable, which quietly turns the harness into noise.

### 3.3 Where the judge is not used

Attribution accuracy, groundedness, temporal correctness, and boundary violations are checked **deterministically** against ground truth — not judged. Only genuinely subjective dimensions (usefulness, tone, appropriate hedging) go to the judge. This is both cheaper and more reliable.

---

## 4. The four-stage pipeline

The 2026 production standard, with automated gates at each stage:

### Stage 1 — Local development

Rapid iteration against the golden dataset using a standard harness (DeepEval, Promptfoo, or equivalent). Developers see quality impact before opening a pull request.

### Stage 2 — Pull request

**Fast evaluation only: heuristic checks, ~30 cases, under 60 seconds.**

The time limit is a hard requirement, not a target. Practitioners are explicit that if the fast evaluation exceeds roughly a minute, **developers begin bypassing it** — and a bypassed gate provides zero protection while creating false confidence.

Regression below baseline blocks the merge.

### Stage 3 — Nightly / pre-deploy

Full evaluation: complete golden dataset, LLM judge, all metrics. Threshold-based blocking on accuracy, groundedness, and boundary compliance. Regression from the production baseline halts deployment.

### Stage 4 — Production monitoring

Live traffic sampled continuously and fed back into the golden dataset. The original proposal specified **1% sampling for human review**, which is retained.

Monitored continuously:

- **Groundedness** as an early-warning signal (file 09 §4.3) — it degrades before users complain.
- **Correction rate** — how often users edit their own records. A rise is the clearest available quality alarm, since it comes from the people best positioned to know.
- **Cost per output**, tagged by feature, tenant, and model (file 09 §5.3).

---

## 5. The release gate

**Gate deployment on the metric corresponding to the most expensive failure mode.** For CAIRN that is unambiguous:

| Gate                     | Threshold                        | Rationale                                       |
| ------------------------ | -------------------------------- | ----------------------------------------------- |
| **Boundary violations**  | **Zero. Any occurrence blocks.** | Regulatory exposure (file 05 §B.3.3)            |
| **Attribution accuracy** | No regression from baseline      | Misattribution is the trust-killer (file 01 §5) |
| **Groundedness**         | ≥ target, no regression          | Fabrication is the worst user-visible failure   |
| **Factual accuracy**     | > 90% on the golden set          | The original proposal's stated target, retained |
| **Tone compliance**      | Zero violations                  | File 05 §A.5                                    |

Everything else is tracked and reviewed, but does not block.

---

## 6. Failure mode taxonomy

Every failure is categorized rather than merely counted. Category frequency drives prioritization — three fabrications and thirty tone issues are very different problems requiring different fixes, and an undifferentiated failure count hides that.

The taxonomy is the §1 table, extended as new modes emerge in production. **New categories are expected**; their appearance is a normal signal, not evidence the framework failed.

---

## 7. Instrumentation

Every pipeline stage is instrumented with **OpenTelemetry**, per current production practice. This makes it possible to answer, for any bad output: which stage produced the error, what context was retrieved, which model ran, what it cost, and how long it took.

Without stage-level tracing, debugging a four-stage pipeline (file 09 §2) degrades into guesswork.

---

## 8. Operating rhythm

| Cadence             | Activity                                                                                                                                                                                     |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Every PR**        | Fast evaluation, under 60 seconds                                                                                                                                                            |
| **Nightly**         | Full golden dataset with judge                                                                                                                                                               |
| **Weekly**          | Quality and cost review together — the original proposal's weekly cost review, extended to quality, since the two trade against each other and reviewing either alone produces bad decisions |
| **Monthly**         | Golden dataset expansion from production corrections; failure taxonomy review                                                                                                                |
| **On model change** | Full re-baseline plus judge re-calibration (§3.1)                                                                                                                                            |

---

## 9. Why this is a competitive advantage, not overhead

It would be easy to read this file as engineering discipline with no market value. It is not:

1. **It is the moat.** The original proposal identified the proprietary evaluation dataset as a defensible asset. Built from real corrections by real teams (§2.1), it is genuinely unavailable to competitors — they cannot access CAIRN's specific pattern of failures and fixes.
2. **It enables the trust positioning.** File 05's commitments are claims. This framework is the evidence, and enterprise AI-governance review (file 05 §B.6) increasingly asks for exactly this.
3. **It permits confident iteration.** Without it, every model or prompt change is a gamble, and teams stop improving the system out of fear of silent breakage.
4. **It is required for the AI Act posture.** Should classification ever be contested, documented evaluation, bias awareness, and human oversight are what a credible response is built from.

---

## Decisions requested from founder

1. **Build the harness before scaling the pipeline** (§intro) — confirm evaluation infrastructure is built alongside the first Understanding layer work, not retrofitted after launch. _Recommendation: confirm._ This is the single most commonly skipped investment in AI products, and the original proposal already identified it as non-negotiable.
2. **Zero-tolerance boundary gate** (§5) — confirm that any scoring, ranking, or allocation output blocks release outright, with no threshold or exception path.
3. **Corrections as evaluation data** (§2.1) — confirm user corrections feed the golden dataset, and that this is disclosed transparently in the Trust & Privacy Center rather than done quietly.
4. **1% production sampling for human review** — confirm the original proposal's rate, and identify who owns that review time weekly.
5. **Dogfooding from month one** (§2.1) — confirm the CAIRN team uses CAIRN on its own work from the earliest possible moment, accepting that this is both the bootstrap dataset and the fastest available quality signal.

---

_Files [09-understanding-layer.md](09-understanding-layer.md) and this one are a pair. The engine without the harness degrades silently; the harness without the engine measures nothing. Neither should be scheduled independently of the other._
