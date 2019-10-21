#!/bin/sh

./render.py default.yaml.template config/secrets_local.yaml config/LOCAL.yaml
./render.py linker.yaml.template config/secrets_local.yaml config/LOCAL.yaml
./render.py adapter.yaml.template config/secrets_local.yaml config/LOCAL.yaml
./render.py admin.yaml.template config/secrets_local.yaml config/LOCAL.yaml
./render.py orchestrator.yaml.template config/secrets_local.yaml config/LOCAL.yaml
./render.py api.yaml.template config/secrets_local.yaml config/LOCAL.yaml

export PUBSUB_EMULATOR_HOST=localhost:8171
python pubsub_topic_creator.py

dev_appserver.py dispatch.yaml default.yaml linker.yaml adapter.yaml admin.yaml orchestrator.yaml api.yaml --port 8080 --admin_port 9000 --logs_path /tmp/gae_gl_ingester.log --log_level=debug --support_datastore_emulator=true --datastore_emulator_port=7171 --enable_console
