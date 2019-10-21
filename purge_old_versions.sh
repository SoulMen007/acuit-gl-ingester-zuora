#!/bin/bash
# Number of app engine versions to be retained.
THRESHOLD=10

if [ -z "$1" ];
then
   echo "[ WARN ] Argument 'projectid' not supplied"
   echo "[ Usage ] $0 <gcloud project id> [Number of Versions to retain]"
   echo "[ Usage ]     (String) gcloud project id is mandatory"
   echo "[ Usage ]     (Positive Integer) Number of versions to retain is optional parameter."
   echo "[ Usage ]       if this parameter is not specified, default is '$THRESHOLD'"
   exit 1
else
  project=$1
  op=$(gcloud projects list --format="value(projectId)" --filter="projectid=$project")
  if [ "$op" == "$project" ];
  then
    echo "[ Info ] Setting the project Id '$project'"
    gcloud config set project $project
  else
    echo "[ WARN ] Project id '$project' is not valid"
    echo "[ Info ] Please provide a valid gcloud project Id"
    exit 1
  fi
fi

if [ -z "$2" ];
then
  echo "[ Info ]Argument 'versionThreshold' not supplied, using default value of '$THRESHOLD'"
  versionThreshold=$THRESHOLD
else
  versionThreshold=$2
fi

# excluding the heading line with 'sed'
gcloud app services list | sed -n -e '2,$p' > ${project}_serviceList

if [ -s ${project}_serviceList ];
then
  while read -r serviceLine; do
    readLine=$serviceLine
    serviceName=$(echo $readLine | cut -d" " -f1)
    versions=$(echo $readLine | cut -d" " -f2)
    echo "[ Info ] Service '$serviceName' has '$versions' versions"
    if [ $versions -gt $versionThreshold ];
    then
      echo "[ Info ] Service '$serviceName' has morethan '$versionThreshold' versions"
      gcloud app versions list --filter="service=$serviceName" --format="table(id,project,service,traffic_split,version.createTime.date('%d-%m-%Y'),version.servingStatus)" --sort-by ~id | sed -n -e "$((versionThreshold+2)),$ p" > ${project}_${serviceName}_versionsList

      if [ -s ${project}_${serviceName}_versionsList ]; then
        while read -r versionLine; do
          readLine=$versionLine
          version=$(echo $readLine|cut -d" " -f1)
          status=$(echo $readLine|cut -d" " -f6)

          if [ "$status" == "SERVING" ];
          then
            serving+=$version" "
          else
            stopped+=$version" "
          fi
        done < ${project}_${serviceName}_versionsList

        if [ -n "$stopped" ] || [ -n "$serving" ];
        then
          gcloud app versions delete -q -s $serviceName ${stopped}${serving}
        else
          echo "[ Info ] There are no versions to be deleted!"
        fi
      else
        echo "[ Info ] No versions available to process "
      fi
    else
      echo "[ Info ] Project = '$project'  & service = '$serviceName'"
      echo "[ Info ] Number of versions '$versions' is less than versions to retain '$versionThreshold'"
    fi
  done < ${project}_serviceList
else
  echo "[ Info ] No services available to process"
fi

