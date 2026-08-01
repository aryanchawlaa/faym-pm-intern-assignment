# Faym.co — PM Intern Shortlisting Assignment

Submission by **Aryan** — August 2026.

Two parts, both fully self-contained and reproducible.

## Part A — Wallet Transactions Case Study

SQL + statistical analysis over the provided 501-row wallet-transactions dataset.

```
analysis.py     Runs every SQL query, computes statistics, generates the chart.
dataset.csv     Cleaned dataset (501 rows, extracted from the provided PDF).
```

Reproduce every answer in the report:

```bash
pip install pandas matplotlib
python analysis.py
```

## Part B — Return Automation Agent

Browser agent that reads pending return tasks from Excel, executes the correct
return flow per platform (Amazon or Flipkart), and writes results back per line
item — crash-safe, partial-success-safe, with bot-detection avoidance.

```
return_agent/
├── agent.py                       Main runner: loads Excel, groups by order, dispatches
├── browser.py                     Persistent Playwright session + stealth patches + human pacing
├── excel_io.py                    openpyxl-based per-row write-back
├── platforms/
│   ├── base.py                    Abstract PlatformAdapter contract
│   ├── flipkart.py                Sequential flow + OTP-driven login
│   └── amazon.py                  Auto-detects batch vs sequential per order
├── returns_queue_template.xlsx    Sample Excel with 5 test rows
├── requirements.txt
└── README.md                      Install / run / architecture notes
```

Run:

```bash
cd return_agent
pip install -r requirements.txt
playwright install chromium
python agent.py --excel returns_queue_template.xlsx
```

See `return_agent/README.md` for the full architecture and design rationale.

## Deliverable Document

`Faym_PM_Intern_Assignment_Aryan.docx` — the full write-up: SQL answers, stats
summary, cohort matrices, and the PRD framing for the return agent.

## Repo Structure

```
.
├── Faym_PM_Intern_Assignment_Aryan.docx    Main deliverable (report)
├── analysis.py                              Part A reproducible script
├── dataset.csv                              Part A input data
├── return_agent/                            Part B code
└── README.md                                This file
```
