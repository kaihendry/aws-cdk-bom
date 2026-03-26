export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION = true

.PHONY: install synth test deploy bom

install:
	uv sync

synth:
	uv run cdk synth

test:
	uv run pytest tests/unit/ -v

deploy:
	uv run cdk deploy

bom: synth
	python3 -c "import json,sys; t=json.load(open('cdk.out/AwsCdkBomStack.template.json')); print(json.dumps(t['Metadata']['BOM'], indent=4))"
