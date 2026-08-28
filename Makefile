.PHONY: demo lab lab-build test verify

demo:
	python -m rigorgate.demo

lab-build:
	python -m rigorgate.replay_lab --build-only

lab: lab-build
	python -m rigorgate.replay_lab --serve

test:
	python -m unittest discover -s tests -v

verify: lab-build
	python -m compileall -q rigorgate run_scan.py run_events.py
	python -m unittest discover -s tests -v
	python -m rigorgate.demo > /tmp/rigorgate-demo.json
	git diff --exit-code -- lab/data/replay.json
