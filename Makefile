.PHONY: install run test overlay collect
PYTHON ?= python3
install:
	$(PYTHON) -m pip install -e '.[test]'
run:
	$(PYTHON) -m terminus serve --host 127.0.0.1 --port 8769 --data-dir .local
test:
	$(PYTHON) -m pytest -q
overlay:
	$(PYTHON) desktop/overlay.py --url http://127.0.0.1:8769 --data-dir .local
collect:
	$(PYTHON) agents/collector.py --url http://127.0.0.1:8769 --data-dir .local
