"""
Migration script for NEXTAPI-1758. Adds the provider_config to all organizations.
"""
from google.cloud import datastore
import argparse

API_PROVIDERS = ['qbo']

def main(project_id, provider, app_family, dry_run=True):
    """
    Assigns all organizations a specified ProviderConfig
    """

    print "DRY_RUN = ", dry_run

    client = datastore.Client(project_id)
    org_keys_only_query = client.query(kind='Org')
    org_keys_only_query.keys_only()

    provider_config_query = client.query(kind='ProviderConfig')
    provider_config_query.add_filter('provider', '=', provider)
    provider_config_query.add_filter('app_family', '=', app_family)

    update_provider_configs_on_orgs(client, list(org_keys_only_query.fetch()), list(provider_config_query.fetch(1))[0], dry_run)


def update_provider_configs_on_orgs(client, org_keys, provider_config, dry_run):
    """
    Transactionally updates all orgs with the given ProviderConfig

    Args:
        client: (Datastore.Client) The datastore client
        org_keys: (Entity) Retrieved `Org` Keys
        provider_config: (Entity) The `ProviderConfig` to assign to all `Org` Entities
        dry_run: (bool) Whether this is a dry run or not
    """

    print ('Assigning all orgs the following provider_config {}'.format(provider_config))

    for org_entity in org_keys:
        with client.transaction():

            org = client.get(org_entity.key)

            if org.get('provider') in API_PROVIDERS:
                print('processing {}'.format(org.key.name))
                org.update({"provider_config": provider_config.key})

                if not dry_run:
                    client.put(org)


def str_to_bool(value):
    if value.lower() in ['false']:
        return False
    elif value.lower() in ['true']:
        return True
    raise ValueError('{} is not a valid boolean value'.format(value))


if __name__ == '__main__':

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--project_id',
        required=True,
        help='The target project ID'
    )

    parser.add_argument(
        '--config_provider',
        required=True,
        help='The provider of the config'
    )

    parser.add_argument(
        '--app_family',
        required=True,
        help='The ProviderConfig app_family'
    )

    parser.add_argument(
        '--is_dry_run',
        help='Whether this migration is a dry run',
        type=str_to_bool,
        default=True
    )

    args = parser.parse_args()

    main(args.project_id, args.config_provider, args.app_family, args.is_dry_run)


