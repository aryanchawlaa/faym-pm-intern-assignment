<div align="center">

# Faym.co — PM Intern Shortlisting Assignment

**A response by Aryan Chawla · August 2026**

*Two problems. A wallet-transactions dataset that needed real analysis, and a browser automation agent that needed to be designed like a product, not a script.*

</div>

---

## What was asked

Faym.co — a creator-commerce platform connecting India's next generation of creators with e-commerce brands — sent a two-part shortlisting task for the Product Management Intern role.

**Part A** was analytical: five SQL questions on a 501-row wallet-transactions dataset spanning January to July 2020, plus a distribution analysis and a monthly cohort matrix.

**Part B** was product thinking: design a browser agent that automates the return process for multi-item Amazon and Flipkart orders — a problem where a single "return" can span three products, two platforms, and two entirely different UI flows, and where the automation itself risks getting the account flagged as a bot.

The full write-up sits in [**Faym_PM_Intern_Assignment_Aryan.docx**](./Faym_PM_Intern_Assignment_Aryan.docx). This repository is where the work behind those pages lives.

---

## Part A — What the data actually said

The wallet-transactions dataset covered **10 users, 7 months, 5 rails, and ₹25 lakh in flow**. Rather than answer each question in isolation, I treated it as a mini-analytics engagement — every number in the report was computed against the actual data in SQLite, not eyeballed.

**A few things stood out once the queries ran:**

- **IMPS dominates.** 54% of all transactions rode IMPS rails — more than IFT, UPI, NEFT and RTGS combined. For a wallet product this is a strong signal about which integrations to prioritise.
- **The user base is small but sticky.** In the January cohort of 8 debit-active users, retention ran between 5 and 8 every single month through July. A tiny sample, but every one of those users stayed.
- **Every user runs a negative net position.** Across all 10 users, CREDIT volume consistently exceeds DEBIT volume — classic load-heavy wallet behaviour. This reframes what "highest net amount" even means (least negative, not most positive), which I called out in the report so the reader wasn't misled.
- **Ambiguity handled explicitly.** "Load amount" could mean *all transactions* or *CREDIT-only wallet loads*. Rather than pick one and hope, I computed and presented both. Same for the cohort definition — first-DEBIT-month vs first-any-transaction-month. Both are in the report.

A reader who wants to trust the numbers can run `python analysis.py` and see them regenerate live.

---

## Part B — Designing the return agent as a product

The engineering brief described a browser bot. I read it as a product problem in disguise, because the interesting decisions weren't about which button to click — they were about **what happens when things go wrong.**

**The three product-level questions I chose to answer in the PRD:**

**1. What is a "unit of work"?**
A single Amazon order can contain five SKUs. Some are past their return window, some aren't. Some platforms let you return them in a single batch flow, others force you to do it one SKU at a time. The obvious answer — "the order" — is wrong. The right answer is **one line item = one tracked outcome**, and every design decision falls out of that: the Excel schema is per-SKU, the agent yields results per-SKU, the write-back to Excel happens per-SKU, the "done" rollup only fires when every SKU has a final state.

**2. What does "the agent got stuck" look like?**
The brief bonus-marks bot avoidance, but the deeper question is: what should the agent do when a platform *thinks* it's a bot? Retry loops are the wrong answer — repeated failed attempts against a CAPTCHA screen are themselves one of the strongest bot signals a platform tracks. So the agent's failure mode is deliberate: **hit a challenge, flag the remaining items for human review, move on.** No retries against verification pages, ever.

**3. What's the boundary between "automated" and "supervised"?**
Flipkart's test account uses OTP-based login. I didn't try to be clever with SMS interception — that's brittle and it's also the kind of thing that gets accounts banned. Instead the login flow is explicitly a supervised step: the agent requests the OTP, a human channel supplies it. Automation should stop at the door of anything a real human would need to physically approve.

The **PRD in the deliverable document** walks through this properly, with goals, non-goals, success metrics, risks, and a phased rollout plan starting on the provided Flipkart test account.

---

## What's in this repository

| | |
|---|---|
| **[Faym_PM_Intern_Assignment_Aryan.docx](./Faym_PM_Intern_Assignment_Aryan.docx)** | The full submission — Part A answers with methodology, Part B as a proper PRD |
| **[analysis.py](./analysis.py)** + **[dataset.csv](./dataset.csv)** | The reproducible Part A analysis — every SQL query, every stat, every chart |
| **[return_agent/](./return_agent/)** | A working Python + Playwright implementation of the agent described in the PRD — because writing a spec is easy, and code makes it real |

---

## A note on the code

The `return_agent/` folder isn't a scaffold — it's the design decisions from the PRD, executed:

- Adapter pattern per platform (adding Myntra or Meesho later = one new file).
- Auto-detection of batch vs sequential return model at the order level.
- Per-row write-back to Excel that survives a mid-run crash without losing progress.
- Stealth measures (persistent browser profile, fingerprint patches, human-scale pacing) — not because a script needs them, but because a *product* running against live Amazon and Flipkart does.

I didn't run it against a real order — that would risk flagging the Flipkart test account the brief provided, which felt like the wrong first move. But every non-live-site behaviour is tested end-to-end with a mock adapter, and I've documented in the return_agent README exactly which parts are proven-solid vs which parts (the CSS selectors) would need one hour of real-order verification on day one.

---

## About this submission

Written under the deadline provided (submission due Sunday 2 August 2026, sent Wednesday 30 July 2026). The intent was to treat the assignment the way I'd treat a real first week on the job — take the brief seriously, ask the questions the brief left open, and ship something a hiring manager could actually use.

If any of this is worth a longer conversation, I'd be glad to walk through it on a call.

<div align="center">

**Aryan Chawla** · ankitaryanchawla@gmail.com

</div>
