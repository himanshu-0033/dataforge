# Windows: use `make` from Git Bash, or run the python commands directly.
PY ?= python

.PHONY: preflight dev eval eval-dry test clean

preflight:            ## gate: key + live catalog + one real synth in both formats
	$(PY) preflight.py

dev: ## run the agent at http://localhost:8765
	$(PY) server.py

eval: ## acceptance test against live Rime audio -> out/eval.csv
	$(PY) eval.py -n 10 --formats L16,PCMU -o out/eval-live.csv

eval-dry: ## same matrix, synthetic durations, no API key
	$(PY) eval.py --dry -n 10 -o out/eval-dry.csv

test: ## pure-logic self-check of the heard ledger
	$(PY) ledger.py
	$(PY) -m unittest -v test_workflow test_conversation

clean:
	rm -rf out __pycache__
