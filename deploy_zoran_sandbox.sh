#!/bin/sh

if [ -d "htmlcov" ]; then
	rm -r htmlcov
fi

./render.py default.yaml.template config/secrets_local.yaml config/zoran_sandbox.yaml
./render.py linker.yaml.template config/secrets_local.yaml config/zoran_sandbox.yaml
./render.py adapter.yaml.template config/secrets_local.yaml config/zoran_sandbox.yaml
./render.py admin.yaml.template config/secrets_local.yaml config/zoran_sandbox.yaml
./render.py orchestrator.yaml.template config/secrets_local.yaml config/zoran_sandbox.yaml
./render.py api.yaml.template config/secrets_local.yaml config/zoran_sandbox.yaml
./render.py cron.yaml.template cron/SANDBOX.yaml

gcloud --project=acuit-zoran-wins-sandbox app deploy cron.yaml index.yaml dispatch.yaml queue.yaml default.yaml linker.yaml adapter.yaml admin.yaml orchestrator.yaml api.yaml --stop-previous-version
