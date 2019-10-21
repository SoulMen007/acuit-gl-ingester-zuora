"""
Migration script for NEXTAPI-1625. Adds linked_at and connected_at fields to Org kind.
"""
import sys
from google.cloud import datastore


def main(project_id):
    """
    Adds linked_at and connected_at fields to Org kind entries which do not have the fields already. It uses the
    created_at value for linked_at and connected_at as that's the best guess we have.
    """
    client = datastore.Client(project_id)
    query = client.query(kind='Org')

    for org in query.fetch():
        print("processing {}".format(org.key.name))
        save = False

        if org.get('linked_at'):
            print("  linked_at already exists ({})".format(org['linked_at']))
        else:
            print("  setting linked_at to {}".format(org['created_at']))
            org['linked_at'] = org['created_at']
            save = True

        if org.get('connected_at'):
            print("  connected_at already exists ({})".format(org['connected_at']))
        else:
            print("  setting connected_at to {}".format(org['created_at']))
            org['connected_at'] = org['created_at']
            save = True

        if save:
            client.put(org)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("usage: migrate.py PROJECT_ID")
        print("       PROJECT_ID example: acuit-gl-sync-dev")
        exit(1)

    main(sys.argv[1])
