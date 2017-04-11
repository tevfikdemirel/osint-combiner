from netaddr import IPNetwork, AddrFormatError
from elasticsearch import Elasticsearch
from elasticsearch import exceptions
from collections import OrderedDict
from pathlib import Path
import configparser
import argparse
import string
import json
import sys
import os
import re


def get_es_cluster_ip():
    """Returns the Elasticsearch IP from config.ini"""
    config = configparser.ConfigParser()
    config.read(os.path.dirname(os.path.realpath(__file__)) + "/config.ini")
    return config['elastic']['ELASTICSEARCH_IP']


def get_xpack_credentials():
    """Returns x-pack credentials from config.ini"""
    config = configparser.ConfigParser()
    config.read(os.path.dirname(os.path.realpath(__file__)) + "/config.ini")
    return config['elastic']['X-PACK_USERNAME'], config['elastic']['X-PACK_PASSWORD']


def xpack_enabled():
    """Returns whether x-pack is enabled from config.ini"""
    config = configparser.ConfigParser()
    config.read(os.path.dirname(os.path.realpath(__file__)) + "/config.ini")
    return config['elastic']['X-PACK_ENABLED']


def get_es_object():
    """Returns Elasticsearch object"""
    if xpack_enabled():
        credentials = get_xpack_credentials()
        return Elasticsearch([get_es_cluster_ip()], http_auth=(credentials[0], credentials[1]))
    else:
        return Elasticsearch(([{'host': get_es_cluster_ip()}]))


def es_get_all_ips(str_existing_index):
    """Returns list of list_of_ips stored in given Elasticsearch index"""
    list_ips = []
    es = get_es_object()
    count = es.count(index=str_existing_index)['count']
    res = es.search(index=str_existing_index,
                    body={"size": 0, "aggs": {"all_ip": {"terms": {"field": "ip", "size": count}}}})
    for key in res['aggregations']['all_ip']['buckets']:
        list_ips.append(key['key'])
    print('Found ' + str(len(list_ips)) + ' IPs in Elasticsearch index ' + str_existing_index)
    ask_continue()
    return list_ips


def es_get_ips_by_query(str_existing_index):
    """Returns list of ips from query stored in given Elasticsearch index
    The query body in this function needs to be edited hardcoded.
    """
    list_ips = []
    es = get_es_object()
    count = es.count(index=str_existing_index)['count']
    res = es.search(index=str_existing_index,
                    body={"size": 0, "aggs": {"ips_by_query": {"terms": {"field": "ip", "size": count}}}, "query":
                        {"query_string": {"query":"\"cisco-IOS\" OR \" Cisco Systems\"", "analyze_wildcard": "true"}}})
    for key in res['aggregations']['ips_by_query']['buckets']:
        list_ips.append(key['key'])
    print('Found ' + str(len(list_ips)) + ' IPs by query in Elasticsearch index ' + str_existing_index)
    ask_continue()
    return list_ips


def es_get_all(str_existing_index):
    """Returns all documents stored in given Elasticsearch index"""
    documents = []
    es = get_es_object()
    count = es.count(index=str_existing_index)['count']
    res = es.search(index=str_existing_index,
                    body={"query": { "match_all": {}}, "size": count})
    for key in res['hits']['hits']:
        documents.append(key)
    print('Found ' + str(len(documents)) + ' IPs in Elasticsearch index ' + str_existing_index)
    ask_continue()
    return documents


def exists_es_index(str_valid_index):
    """Returns if given index exists in Elasticsearch cluster"""
    connection_attempts = 0
    while connection_attempts < 3:
        try:
            es = get_es_object()
            es_indices = es.indices
            return es_indices.exists(index=str_valid_index)
        except exceptions.ConnectionTimeout:
            connection_attempts += 1
    print('Elasticsearch connection timeout, exiting now...')
    sys.exit(1)


def get_cidr_from_user_input():
    """Parses one CIDR from user input and returns IPNetwork"""
    ip_or_cidr = '0'
    while not isinstance(ip_or_cidr, IPNetwork):
        try:
            ip_or_cidr = IPNetwork(input('IP/CIDR: '))
        except AddrFormatError:
            print('Not a valid IP/CIDR.')
    return ip_or_cidr


def parse_all_cidrs_from_file(file_path, assume_yes):
    """Returns set of CIDR strings from given file"""
    output = set()
    while not output:
        with open(file_path) as f:
            output = set(re.findall('(?:\d{1,3}\.){3}\d{1,3}(?:/\d\d?)?', f.read()))
            print('CIDRs Found:' + str(output))
            print('Total CIDRs in file: ' + str(len(output)))
            if not assume_yes:
                ask_continue()
    return output


def is_valid_file_name(str_input):
    """Returns if str is valid file name.
    May only contain: ascii_lowercase, ascii_uppercase, digits, dot, dash, underscore
    """
    allowed = set(string.ascii_lowercase + string.ascii_uppercase + string.digits + '.-_')
    if str_input is not '':
        return set(str_input) <= allowed
    return False


def is_valid_es_index_name(str_input):
    """Returns if str is valid Elasticsearch index name.
    May only contain: ascii_lowercase, digits, dash, underscore
    """
    allowed = set(string.ascii_lowercase + string.digits + '-_')
    if str_input is not '':
        return set(str_input) <= allowed
    return False


def dict_add_source_prefix(obj, source_str, shodan_protocol_str=''):
    """Return dict where any non-nested element (except 'ip and ip_int') is prefixed by the OSINT source name"""
    keys_not_source_prefixed = ['ip', 'asn', 'ip_int']
    # These will still have the source prefixed
    shodan_keys_not_protocol_prefixed = ['asn', 'ip', 'ipv6 port', 'hostnames', 'domains', 'location',
                                                'location.area_code', 'location.city', 'location.country_code',
                                         'location.country_code3', 'location.country_name', 'location.dma_code',
                                         'location.latitude', 'location.longitude', 'location.postal_code',
                                         'location.region_code', 'opts', 'org', 'isp', 'os', 'transport', 'protocols']
    for key in list(obj):
        # prefix all non-nested elements except ip and ip_int
        if '.' not in key and key not in keys_not_source_prefixed:
            # if other OSINT than Shodan, just prefix source
            if shodan_protocol_str is '':
                new_key = key.replace(key, (source_str + "." + key))
            # if shodan
            else:
                # just prefix source if general shodan key
                if key in shodan_keys_not_protocol_prefixed:
                    new_key = key.replace(key, (source_str + "." + key))
                # prefix source AND shodan.module (protocol) if protocol-specific key
                else:
                    new_key = key.replace(key, (source_str + "." + shodan_protocol_str + '.' + key))
            if new_key != key:
                obj[new_key] = obj[key]
                del obj[key]
    return obj


def print_json_tree(df, indent='  '):
    """Prints tree structure of given dict for test/debug purposes"""
    for key in df.keys():
        print(indent+str(key))
        if isinstance(df[key], dict):
            print_json_tree(df[key], indent + '   ')


def dict_clean_empty(d):
    """Returns dict with all empty elements removed, value 0 retained"""
    if not isinstance(d, (dict, list)):
        return d
    if isinstance(d, list):
        return [v for v in (dict_clean_empty(v) for v in d) if v]
    return {k: v for k, v in ((k, dict_clean_empty(v)) for k, v in d.items()) if v or v == 0}


def ask_input_file(path_prefix=''):
    """Returns existing file from user input"""
    input_file = Path('')
    input_file_path = ''
    while not input_file.is_file():
        input_file_path = input('Input file:' + path_prefix)
        input_file = Path(path_prefix + input_file_path)
    return input_file


def ask_input_directory():
    """Returns existing directory from user input"""
    input_directory = ''
    while not os.path.isdir(input_directory):
        input_directory = input('Input directory:')
    return input_directory


def ask_output_file(str_prefix_output_file):
    """Returns valid file path string for new file from user input"""
    str_name_output_file = ''
    while not is_valid_file_name(str_name_output_file):
        str_name_output_file = input('Output file:' + str_prefix_output_file)
    str_output_file = str_prefix_output_file + str_name_output_file
    return increment_until_new_file(str_output_file)


def increment_until_new_file(str_file):
    """Will increment given file path with number until file path does not exist yet"""
    i = 0
    str_final_file = str_file
    while os.path.exists(str_final_file):
        i += 1
        str_final_file = os.path.dirname(str_file) + '/' + os.path.splitext(os.path.basename(str(str_file)))[
            0] + str(i) + os.path.splitext(os.path.basename(str(str_file)))[1]
    return str_final_file


def get_organizations_from_csv(str_path_csv_file):
    """Returns OrderedDict containing organizations with CIDRS from given CSV file"""
    list_organizations = OrderedDict()
    f = open(str_path_csv_file, 'r')
    for line in f:
        line = line.split(',')
        if line[0] not in list_organizations:
            list_organizations[line[0]] = [line[1]]
        else:
            list_organizations[line[0]].append(line[1])
    return list_organizations


class ConcatJSONDecoder(json.JSONDecoder):
    """Returns list of dicts from given string containing multiple root JSON objects"""
    # shameless copy paste from element/decoder.py
    FLAGS = re.VERBOSE | re.MULTILINE | re.DOTALL
    WHITESPACE = re.compile(r'[ \t\n\r]*', FLAGS)

    def decode(self, s, _w=WHITESPACE.match):
        s_len = len(s)
        objs = []
        end = 0
        while end != s_len:
            obj, end = self.raw_decode(s, idx=_w(s, end).end())
            end = _w(s, end).end()
            objs.append(obj)
        return objs


def ask_continue():
    """Asks user if script should continue or stop immediately"""
    if get_user_boolean('Continue? y/n') is False:
        sys.exit(0)


def get_user_boolean(text):
    """Returns boolean from user input. Accepts only y (True) or n (False)"""
    while True:
        str_should_convert = input(text)
        if str_should_convert is 'y':
            return True
        elif str_should_convert is 'n':
            return False


def get_option_from_user(question, list_str_options):
    """Asks user input with given question, returns one of given options"""
    answer = ''
    while answer not in list_str_options:
        answer = input(question)
    return answer


def create_output_directory(input_directory):
    """Creates new directory and returns its path"""
    output_directory = ''
    increment = 0
    done_creating_directory = False
    while not done_creating_directory:
        try:
            if input_directory.endswith('/'):
                output_directory = input_directory + 'converted'
            else:
                output_directory = input_directory + '/converted'
            if increment is not 0:
                output_directory += str(increment)
            os.makedirs(output_directory, exist_ok=False)
            done_creating_directory = True
        except FileExistsError:
            increment += 1
    return output_directory


def get_queries_per_line_from_file(str_path_input_file):
    """Returns list of queries as string, without any blank lines"""
    with open(str_path_input_file) as f_in:
        return list(filter(None, (line.rstrip() for line in f_in)))


def check_exists_input_file(str_file_path):
    """Checks if input file exists"""
    if not Path(str_file_path).is_file():
        msg = "{0} is not an existing file".format(str_file_path)
        raise argparse.ArgumentTypeError(msg)


def get_input_choice(args):
    """Check if an input choice is given"""
    try:
        return args.subparser
    except AttributeError:
        msg = 'Missing input choice.'
        raise argparse.ArgumentTypeError(msg)


def check_outputfile(str_file_path):
    """Check if output file can be created"""
    try:
        open(str_file_path, "a")
    except FileNotFoundError:
        msg = 'Cannot create outputfile. Do all directories in outputfile path exist?'
        raise argparse.ArgumentTypeError(msg)


def get_path_converted_output_file(str_path_input_file):
    """Returns a path for converted outputfile"""
    input_file = Path(str_path_input_file)
    return increment_until_new_file('converted_outputfiles/' + os.path.splitext(os.path.basename(str(input_file)))[0]
                                    + '-converted' + os.path.splitext(str(input_file))[1])


def convert_file(str_path_input_file, source_type):
    """Converts given inputfile to outputfile"""
    from shodanfunctions import shodan_to_es_convert
    from censysfunctions import censys_to_es_convert
    from ipinfofunctions import ipinfo_to_es_convert
    str_path_output_file = get_path_converted_output_file(str_path_input_file)
    with open(str_path_output_file, 'a', encoding='utf-8') as output_file:
        input_file = Path(str_path_input_file)
        for str_banner in input_file.open(encoding='utf-8'):
            if str_banner != '\n':
                try:
                    banner = dict_clean_empty(json.loads(str_banner))
                    if source_type is 'shodan':
                        shodan_to_es_convert(banner)
                    elif source_type is 'censys':
                        censys_to_es_convert(banner)
                    elif source_type is 'ipinfo':
                        ipinfo_to_es_convert(banner)
                    output_file.write(json.dumps(banner) + '\n')
                except json.decoder.JSONDecodeError as e:
                    print(e.args)
                    print('Malformed json: ' + str_banner)
    print('Converted ' + str_path_input_file + ' to ' + str_path_output_file)


