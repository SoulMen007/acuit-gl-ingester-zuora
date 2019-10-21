# acuit-gl-ingester

App Engine Standard project containing services facilitating ingestion part of the V3 platform ingestion pipe (more
details [on the wiki](https://pwcnext.atlassian.net/wiki/spaces/~aert.van.de.hulsbeek/pages/382959655/Ingestion+V3)).

This project is responsible for landing of GL data in an intermediary storage, ready for the subsequent normalisation
and publishing of this data.


# Running locally

Install dependencies (using virtual environment is recommended):
```
pip install -r lib_requirements.txt -t lib --upgrade
pip install -r requirements.txt
```

Provide QBO and Xero app details in `config/secrets_local.yaml`:
```
QBO_CLIENT_ID: "the_best_app_ever"
QBO_CLIENT_SECRET: "dont_tell_anyone"
XERO_CONSUMER_KEY: "no_im_the_best_app_ever"
XERO_CONSUMER_SECRET: "i_wont_tell"
```

Start the app with `./run_server.sh`, and go to [http://localhost:8080/admin/](http://localhost:8080/admin/).

Good luck!

# Running tests

Run the tests with `./run_tests.py ~/.local/google-cloud-sdk/`.

For code coverage report run the following `coverage run run_tests.py ~/.local/google-cloud-sdk/; coverage html` (but
you have to `pip install coverage` first). Open `htmlcov/index.html` to view the report.

# Datastore backups

Datastore backups are initiated by the `default` service via the `/cloud-datastore-export` endpoint which it invoked by
a cron job. The backup schedule is defined in `cron/<ENV>.yaml` files.
