#!/bin/bash --login

#set -ex
set -e

function get_current_environment {
  case "$CI_BRANCH" in
   dev*) env=dev ;;
   TEST*) env=test ;;
   RC*) env=uat ;;
   REL*) env=prod ;;
   NT-DEV-*) env=dev ;;
   NT-TEST-*) env=test ;;
   NT-RC-*)  env=uat ;;
   NT-REL-*)  env=prod ;;
   *) env=NODEPLOY ;;
 esac
 echo $env
}

function get_switch_traffic {
  case "$CI_BRANCH" in
   dev*) switch_traffic='--promote' ;;
   TEST*) switch_traffic='--promote' ;;
   RC-*) switch_traffic='--promote' ;;
   REL-*) switch_traffic='--promote' ;;
   NT-DEV-*) switch_traffic='--no-promote' ;;
   NT-TEST-*) switch_traffic='--no-promote' ;;
   NT-RC-*)  switch_traffic='--no-promote' ;;
   NT-REL-*)  switch_traffic='--no-promote' ;;
   *) switch_traffic='--no-promote' ;;
 esac
 echo $switch_traffic
}

function prepare {
  echo "[ Info ] Install libs"
  pip install -r lib_requirements.txt -t lib
  pip install -r requirements.txt

  echo "[ Info ] Removing version.txt"
  if [ -f ./app/services/default/version.txt ]; then
    rm ./app/services/default/version.txt
  fi

  # Install Google Cloud SDK
  export CLOUDSDK_PYTHON_SITEPACKAGES=1; export CLOUDSDK_CORE_DISABLE_PROMPTS=1;

  # Set service account key files
  mkdir -p ~/.gcp
  output=SECRETS_SERVICE_ACCOUNT_KEY_${ENVIRONMENT_UPPER}
  eval echo \$$output > ${SECRETS_SERVICE_ACCOUNT_KEY_FILE}
  output=DEPLOYER_SERVICE_ACCOUNT_KEY_${ENVIRONMENT_UPPER}
  eval echo \$$output > ${DEPLOYER_SERVICE_ACCOUNT_KEY_FILE}

  echo "[ Info ] Update gcloud components"
  gcloud components update -q

  echo "[ Info ] Setting project to $PROJECT"
  gcloud config set project $PROJECT


  # Secrets account bit
  # Update the secrets here:
  # https://pwcnext.atlassian.net/wiki/spaces/ACUIT/pages/8357028/Managing+Secrets+-+Code+snippit+examples#ManagingSecrets-Codesnippitexamples-acuit-aggregator-dev
  echo "[ Info ] Activate service account secrets"
  gcloud auth activate-service-account $SECRETS_SERVICE_ACCOUNT --key-file $SECRETS_SERVICE_ACCOUNT_KEY_FILE

  echo "[ Info ] Get secrets"
  curl -v "https://cloudkms.googleapis.com/v1/projects/acuit-0/locations/global/keyRings/$ENVIRONMENT_UPPER/cryptoKeys/${REPOSITORY_NAME}-secrets:decrypt" \
    -d "{\"ciphertext\":\"$(gsutil cat gs://acuit-secrets-$environment/${REPOSITORY_NAME}-${environment}-secrets.yaml.encrypted)\"}" \
    -H "Authorization:Bearer $(gcloud auth print-access-token)" \
    -H "Content-Type:application/json" \
  | jq .plaintext -r | base64 -d > /tmp/${REPOSITORY_NAME}-${environment}-secrets.yaml

  # Deployer account bit from now on
  echo "[ Info ] Activate service account deployer"
  gcloud auth activate-service-account $DEPLOYER_SERVICE_ACCOUNT --key-file $DEPLOYER_SERVICE_ACCOUNT_KEY_FILE


}

function deploy {

  echo "[ Info ] Creating build version info"
  CI_MESSAGE_CLEANED=${CI_MESSAGE//[$'\t\r\n']}

  echo '{'  > ./app/services/default/version.txt
  echo '  "CI_COMMIT_ID": "'${CI_COMMIT_ID}'",' >> ./app/services/default/version.txt
  echo '  "CI": "'${CI}'",' >> ./app/services/default/version.txt
  echo '  "CI_BRANCH":"'${CI_BRANCH}'",' >> ./app/services/default/version.txt
  echo '  "CI_BUILD_NUMBER":"'${CI_BUILD_NUMBER}'",' >> ./app/services/default/version.txt
  echo '  "CI_BUILD_URL":"'${CI_BUILD_URL}'",' >> ./app/services/default/version.txt
  echo '  "CI_COMMITTER_USERNAME":"'${CI_COMMITTER_USERNAME}'",' >> ./app/services/default/version.txt
  echo '  "CI_MESSAGE":"'${CI_MESSAGE_CLEANED}'",' >> ./app/services/default/version.txt
  echo '  "CI_NAME":"'${CI_NAME}'",' >> ./app/services/default/version.txt
  echo '  "CI_REPO_NAME":"'${CI_REPO_NAME}'",' >> ./app/services/default/version.txt
  echo '}' >> ./app/services/default/version.txt

  echo "Preparing service yamls for $ENV..."
  ./render.py default.yaml.template /tmp/${REPOSITORY_NAME}-${environment}-secrets.yaml config/${ENVIRONMENT_UPPER}.yaml
  ./render.py linker.yaml.template /tmp/${REPOSITORY_NAME}-${environment}-secrets.yaml config/${ENVIRONMENT_UPPER}.yaml
  ./render.py adapter.yaml.template /tmp/${REPOSITORY_NAME}-${environment}-secrets.yaml config/${ENVIRONMENT_UPPER}.yaml
  ./render.py admin.yaml.template /tmp/${REPOSITORY_NAME}-${environment}-secrets.yaml config/${ENVIRONMENT_UPPER}.yaml
  ./render.py orchestrator.yaml.template /tmp/${REPOSITORY_NAME}-${environment}-secrets.yaml config/${ENVIRONMENT_UPPER}.yaml
  ./render.py api.yaml.template /tmp/${REPOSITORY_NAME}-${environment}-secrets.yaml config/${ENVIRONMENT_UPPER}.yaml

  echo "Preparing cron for $ENV..."
  ./render.py cron.yaml.template cron/${ENVIRONMENT_UPPER}.yaml /tmp/project.yaml

  echo "Deploying all the stuffs..."
  gcloud app deploy cron.yaml index.yaml dispatch.yaml queue.yaml default.yaml linker.yaml adapter.yaml admin.yaml orchestrator.yaml api.yaml ${traffic}

  echo "Cleaning up indexes..."
  gcloud datastore indexes cleanup index.yaml

  echo "Reverting yamls to LOCAL..."
  ./render.py default.yaml.template config/LOCAL.yaml
  ./render.py linker.yaml.template config/LOCAL.yaml
  ./render.py adapter.yaml.template config/LOCAL.yaml
  ./render.py admin.yaml.template config/LOCAL.yaml
  ./render.py orchestrator.yaml.template config/LOCAL.yaml
  ./render.py api.yaml.template config/LOCAL.yaml

  echo "Done!"

}


##############################################
#    Main
##############################################
environment=$(get_current_environment)
traffic=$(get_switch_traffic)

echo "[ Info ] Environment is '$environment'"
if [ $environment == 'NODEPLOY' ]; then
  echo "[ Info ] Deployment is not required for the branch '$CI_BRANCH'"
  exit
fi

ENVIRONMENT_UPPER="$(echo $environment | tr '[:lower:]' '[:upper:]')"
echo "[ Info ] Environment UPPER is '$ENVIRONMENT_UPPER'"

# hard code the project name here as it can't be derived from the git repo name
REPOSITORY_NAME='acuit-gl-sync'

echo "[ Info ] Repository Name is '$REPOSITORY_NAME'"

if [ $environment == 'prod' ]; then
  PROJECT=${REPOSITORY_NAME}-us-${environment}
elif [ $environment == 'test' ]; then
  PROJECT=${REPOSITORY_NAME}-${environment}-0
else
  PROJECT=${REPOSITORY_NAME}-${environment}
fi
echo "[ Info ] Project is '$PROJECT'"

echo "PROJECT: $PROJECT" >> /tmp/project.yaml

DEPLOYER_SERVICE_ACCOUNT=deployer@${PROJECT}.iam.gserviceaccount.com
DEPLOYER_SERVICE_ACCOUNT_KEY_FILE=$HOME/.gcp/${DEPLOYER_SERVICE_ACCOUNT}.json
SECRETS_SERVICE_ACCOUNT=secrets-${environment}@acuit-0.iam.gserviceaccount.com
SECRETS_SERVICE_ACCOUNT_KEY_FILE=$HOME/.gcp/${SECRETS_SERVICE_ACCOUNT}.json

prepare
deploy

if [ -f "purge_old_versions.sh" ];
then
  chmod +x purge_old_versions.sh
  ./purge_old_versions.sh $PROJECT
else
  echo "[ Info ] Script for purging old app engine versions not available."
fi


