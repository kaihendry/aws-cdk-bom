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

bom:
	aws cloudformation get-template \
	  --stack-name AwsCdkBomStack \
	  --query 'TemplateBody.Metadata.BOM' \
	  --output json
