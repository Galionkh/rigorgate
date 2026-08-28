.PHONY: demo lab lab-build test verify

demo:
	python -m galion.demo

lab-build:
	python -m galion.replay_lab --build-only

lab: lab-build
	python -m galion.replay_lab --serve

test:
	python -m unittest discover -s tests -v

verify: lab-build
	python -m compileall -q galion run_scan.py run_events.py
	python -m unittest discover -s tests -v
	python -m galion.demo > /tmp/galion-demo.json
	git diff --exit-code -- lab/data/replay.json
