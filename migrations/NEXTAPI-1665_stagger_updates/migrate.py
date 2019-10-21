#!/usr/bin/env python

"""
Migration script for NEXTAPI-1665. Adds last_update_cycle_completed_at to Org.
"""
import argparse
from datetime import datetime

from google.cloud import datastore


def main(project_id, save=False):
    if save:
        print("Doing it for realsies!")
    else:
        print("Doing a dry run!")

    client = datastore.Client(project_id)
    query = client.query(kind='Org')

    property = 'last_update_cycle_completed_at'
    value = datetime(1970, 1, 1)

    for org in query.fetch():
        print("processing {}".format(org.key.name))

        if org.get(property):
            print("  {} already exists ({})".format(property, org[property]))
        else:
            print("  setting {} to {}".format(property, value))
            org[property] = value

            if save:
                client.put(org)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--project', help='The project ID you are targeting, e.g. acuit-gl-sync-dev', required=True)
    parser.add_argument('-s', '--save', help='Perform writes (dry run otherwise)', default=False, action='store_true')

    args = parser.parse_args()

    main(args.project, args.save)
