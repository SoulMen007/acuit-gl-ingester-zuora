"""
Module providing utilites for figuring out what date it is in for a particular QBO org. This is done by looking at the
org's country code which is translated to a timezone via the lookup provided by QBO support team.
"""

from datetime import datetime
from pytz import timezone


COUNTRY_TO_TIMEZONE = {
    'AD': 'Europe/Berlin',
    'AE': 'Asia/Dubai',
    'AF': 'Asia/Kabul',
    'AG': 'America/Halifax',
    'AI': 'America/Halifax',
    'AL': 'Europe/Budapest',
    'AM': 'Asia/Yerevan',
    'AN': 'America/Halifax',
    'AO': 'Africa/Lagos',
    'AQ': 'Pacific/Auckland',
    'AR': 'America/Buenos_Aires',
    'AS': 'Etc/GMT+11',
    'AT': 'Europe/Berlin',
    'AU': 'Australia/Sydney',
    'AW': 'America/Halifax',
    'AX': 'Europe/Kiev',
    'AZ': 'Asia/Baku',
    'BA': 'Europe/Warsaw',
    'BB': 'America/Halifax',
    'BD': 'Asia/Dhaka',
    'BE': 'Europe/Paris',
    'BF': 'Atlantic/Reykjavik',
    'BG': 'Europe/Kiev',
    'BH': 'Asia/Dubai',
    'BI': 'Africa/Johannesburg',
    'BJ': 'Africa/Lagos',
    'BL': 'America/La_Paz',
    'BM': 'America/Halifax',
    'BN': 'Asia/Singapore',
    'BO': 'America/La_Paz',
    'BQ': 'America/Halifax',
    'BR': 'America/Sao_Paulo',
    'BS': 'America/New_York',
    'BT': 'Asia/Dhaka',
    'BV': 'Europe/Budapest',
    'BW': 'Africa/Johannesburg',
    'BY': 'Europe/Kaliningrad',
    'BZ': 'America/Chicago',
    'CA': 'America/Los_Angeles',
    'CC': 'Asia/Rangoon',
    'CD': 'Africa/Lagos',
    'CF': 'Africa/Lagos',
    'CG': 'Africa/Lagos',
    'CH': 'Europe/Berlin',
    'CI': 'Etc/GMT',
    'CK': 'Pacific/Honolulu',
    'CL': 'America/Santiago',
    'CM': 'Africa/Lagos',
    'CN': 'Asia/Shanghai',
    'CO': 'America/Bogota',
    'CR': 'America/Chicago',
    'CV': 'Atlantic/Cape_Verde',
    'CW': 'America/Halifax',
    'CX': 'Asia/Bangkok',
    'CY': 'Asia/Nicosia',
    'CZ': 'Europe/Budapest',
    'DE': 'Europe/Berlin',
    'DJ': 'Africa/Nairobi',
    'DK': 'Europe/Budapest',
    'DM': 'America/Halifax',
    'DO': 'America/Halifax',
    'DZ': 'Europe/Warsaw',
    'EC': 'America/Bogota',
    'EE': 'Asia/Nicosia',
    'EG': 'Africa/Cairo',
    'ER': 'Africa/Nairobi',
    'ES': 'Europe/London',
    'ET': 'Africa/Nairobi',
    'FI': 'Europe/Kiev',
    'FJ': 'Pacific/Fiji',
    'FK': 'America/Halifax',
    'FM': 'Pacific/Guadalcanal',
    'FO': 'Atlantic/Reykjavik',
    'FR': 'Europe/Paris',
    'GA': 'Africa/Lagos',
    'GB': 'Europe/London',
    'GD': 'America/La_Paz',
    'GE': 'Asia/Tbilisi',
    'GF': 'America/Cayenne',
    'GG': 'Europe/London',
    'GH': 'Atlantic/Reykjavik',
    'GI': 'Europe/Budapest',
    'GL': 'America/Godthab',
    'GM': 'Atlantic/Reykjavik',
    'GN': 'Atlantic/Reykjavik',
    'GP': 'America/La_Paz',
    'GQ': 'Africa/Lagos',
    'GR': 'Europe/Kaliningrad',
    'GS': 'Etc/GMT+2',
    'GT': 'America/Guatemala',
    'GU': 'Pacific/Port_Moresby',
    'GW': 'Atlantic/Reykjavik',
    'GY': 'America/La_Paz',
    'HK': 'Asia/Shanghai',
    'HM': 'Asia/Tashkent',
    'HN': 'America/Guatemala',
    'HR': 'Europe/Budapest',
    'HT': 'America/New_York',
    'HU': 'Europe/Budapest',
    'ID': 'Asia/Bangkok',
    'IE': 'Europe/London',
    'IL': 'Asia/Jerusalem',
    'IM': 'Europe/London',
    'IN': 'Asia/Calcutta',
    'IO': 'Asia/Almaty',
    'IQ': 'Asia/Baghdad',
    'IS': 'Atlantic/Reykjavik',
    'IT': 'Europe/Berlin',
    'JE': 'Atlantic/Reykjavik',
    'JM': 'America/Bogota',
    'JO': 'Asia/Amman',
    'JP': 'Asia/Tokyo',
    'KE': 'Africa/Nairobi',
    'KG': 'Asia/Almaty',
    'KH': 'Asia/Bangkok',
    'KI': 'Etc/GMT-12',
    'KM': 'Africa/Nairobi',
    'KN': 'America/La_Paz',
    'KR': 'Asia/Seoul',
    'KW': 'Asia/Riyadh',
    'KY': 'America/New_York',
    'KZ': 'Asia/Almaty',
    'LA': 'Asia/Bangkok',
    'LB': 'Asia/Beirut',
    'LC': 'America/La_Paz',
    'LI': 'Europe/Berlin',
    'LK': 'Asia/Colombo',
    'LR': 'Atlantic/Reykjavik',
    'LS': 'Africa/Johannesburg',
    'LT': 'Europe/Kiev',
    'LU': 'Europe/Berlin',
    'LV': 'Europe/Kiev',
    'LY': 'Africa/Johannesburg',
    'MA': 'Africa/Casablanca',
    'MC': 'Europe/Berlin',
    'MD': 'Europe/Bucharest',
    'ME': 'Europe/Budapest',
    'MF': 'America/La_Paz',
    'MG': 'Africa/Nairobi',
    'MH': 'Etc/GMT-12',
    'MK': 'Europe/Warsaw',
    'ML': 'Atlantic/Reykjavik',
    'MM': 'Asia/Rangoon',
    'MN': 'Asia/Ulaanbaatar',
    'MO': 'Asia/Shanghai',
    'MP': 'Pacific/Port_Moresby',
    'MQ': 'America/La_Paz',
    'MR': 'Atlantic/Reykjavik',
    'MS': 'America/La_Paz',
    'MT': 'Europe/Berlin',
    'MU': 'Indian/Mauritius',
    'MV': 'Asia/Tashkent',
    'MW': 'Africa/Johannesburg',
    'MX': 'America/Mexico_City',
    'MY': 'Asia/Singapore',
    'MZ': 'Africa/Johannesburg',
    'NA': 'Africa/Windhoek',
    'NC': 'Pacific/Guadalcanal',
    'NE': 'Africa/Lagos',
    'NF': 'America/Los_Angeles',
    'NG': 'Africa/Lagos',
    'NI': 'America/Guatemala',
    'NL': 'Europe/Berlin',
    'NO': 'Europe/Berlin',
    'NP': 'Asia/Katmandu',
    'NR': 'Etc/GMT-12',
    'NU': 'Etc/GMT+11',
    'NZ': 'Pacific/Auckland',
    'OM': 'Asia/Dubai',
    'PA': 'America/Bogota',
    'PE': 'America/Bogota',
    'PF': 'Pacific/Honolulu',
    'PG': 'Pacific/Port_Moresby',
    'PH': 'Asia/Singapore',
    'PK': 'Asia/Karachi',
    'PL': 'Europe/Warsaw',
    'PM': 'America/St_Johns',
    'PN': 'America/Los_Angeles',
    'PR': 'America/La_Paz',
    'PT': 'Europe/London',
    'PW': 'Asia/Tokyo',
    'PY': 'America/Asuncion',
    'QA': 'Asia/Riyadh',
    'RE': 'Indian/Mauritius',
    'RO': 'Europe/Paris',
    'RS': 'Europe/Budapest',
    'RU': 'Europe/Moscow',
    'RW': 'Africa/Johannesburg',
    'SA': 'Asia/Riyadh',
    'SB': 'Pacific/Guadalcanal',
    'SC': 'Indian/Mauritius',
    'SE': 'Europe/Berlin',
    'SG': 'Asia/Singapore',
    'SH': 'Atlantic/Reykjavik',
    'SI': 'Europe/Budapest',
    'SJ': 'Europe/Berlin',
    'SK': 'Europe/Budapest',
    'SL': 'Atlantic/Reykjavik',
    'SM': 'Europe/Berlin',
    'SN': 'Atlantic/Reykjavik',
    'SO': 'Africa/Nairobi',
    'SR': 'America/Cayenne',
    'SS': 'Africa/Nairobi',
    'ST': 'Atlantic/Reykjavik',
    'SV': 'America/Chicago',
    'SX': 'America/La_Paz',
    'SZ': 'Africa/Johannesburg',
    'TC': 'America/New_York',
    'TD': 'Africa/Lagos',
    'TF': 'Asia/Tashkent',
    'TG': 'Atlantic/Reykjavik',
    'TH': 'Asia/Bangkok',
    'TJ': 'Asia/Tashkent',
    'TK': 'Pacific/Auckland',
    'TL': 'Asia/Tokyo',
    'TM': 'Asia/Tashkent',
    'TN': 'Africa/Lagos',
    'TO': 'Pacific/Tongatapu',
    'TR': 'Europe/Istanbul',
    'TT': 'America/La_Paz',
    'TV': 'Etc/GMT-12',
    'TW': 'Asia/Shanghai',
    'TZ': 'Africa/Nairobi',
    'UA': 'Europe/Kiev',
    'UG': 'Africa/Nairobi',
    'UN': 'America/Los_Angeles',
    'US': 'America/Los_Angeles',
    'UY': 'America/Montevideo',
    'UZ': 'Asia/Tashkent',
    'VA': 'Europe/Berlin',
    'VC': 'America/La_Paz',
    'VE': 'America/Caracas',
    'VG': 'America/La_Paz',
    'VI': 'America/La_Paz',
    'VN': 'Asia/Bangkok',
    'VU': 'Pacific/Guadalcanal',
    'WF': 'Etc/GMT-12',
    'WS': 'Pacific/Apia',
    'XK': 'Europe/Warsaw',
    'YE': 'Asia/Riyadh',
    'YT': 'Africa/Nairobi',
    'ZA': 'Africa/Johannesburg',
    'ZM': 'Africa/Johannesburg',
    'ZW': 'Africa/Johannesburg',
}


def get_org_today(org):
    """
    Provides the current date for the given QBO org.

    Args:
        org(app.services.ndb_models.Org): org object

    Returns:
        date: org's today date
    """
    org_timezone = COUNTRY_TO_TIMEZONE[org.country]
    today = datetime.now(timezone(org_timezone)).date()

    return today
