
# NoCFO Homework Assignment - AI Engineer

This repository contains my solution for the NoCFO homework assignment. The task is to match bank transactions with their related attachments in both directions. The main functions are in `src/match.py`. The file `run.py` prints the report and was not modified.

## How to run

### Requirements
Python 3.10 or newer.

### Setup

```bash
git clone https://github.com/<your-username>/nocfo-homework-assignment-ai-engineer.git
cd nocfo-homework-assignment-ai-engineer

python -m venv .venv
.\.venv\Scripts\Activate.ps1    # Windows PowerShell
# or: source .venv/bin/activate # Linux and macOS
````

No external packages are needed because the solution uses only the Python standard library.

### Run the report

```bash
python run.py
```

The output shows expected matches and the matches found by the code.

## Matching logic

The matching logic is in `src/match.py`. The implementation is split into small helper functions for clarity.

### 1. Reference based matching

If a reference number exists, it is treated as the strongest signal.

Reference numbers are normalized by:

* converting to string
* removing the RF prefix
* removing whitespace
* removing leading zeros
* comparing case insensitively

If exactly one attachment (or transaction) has the same normalized reference, it is returned. If zero or more than one matches exist, the function falls back to heuristics or returns None.

### 2. Heuristic matching

If neither side has a reference, the code uses three signals together:

1. Amount
   Absolute values are compared so invoice totals match outgoing bank amounts. A strong amount match is required.

2. Date
   The difference in days between the transaction date and the attachment date is used. If the gap is too large or the date cannot be parsed, the pair is rejected.

3. Counterparty
   Transaction uses the contact field.
   Attachments use issuer, recipient or supplier.
   Names are normalized by lowercasing, trimming and removing common company suffixes.
   The name similarity is measured with `difflib.SequenceMatcher`. High similarity gives a positive score. If both sides have names but the similarity is zero, the pair is rejected.

All three signals must support the same link for a match.

### 3. Selecting the best candidate

When using heuristics, every possible candidate is scored. Only one candidate is returned if:

* the score is above a threshold
* the best score is clearly higher than the second best

This helps avoid uncertain matches.

## Notes

* Reference numbers take priority when available
* Amount, date and counterparty are treated as equally important when references are missing
* The code uses only standard library modules
* The behavior is deterministic and easy to extend


