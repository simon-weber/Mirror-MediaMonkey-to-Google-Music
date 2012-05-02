import argparse
import appdirs
import os

import sqlite3

import sync2gm

def setup(args):

    sync2gm.init_config(args.confname, args.mp_type, args.mp_db_path)
    



def run(args):
    print "running run!"
    print args


def main():
    parser = argparse.ArgumentParser(description="Sync a local mediaplayer to Google Music.")
    subparsers = parser.add_subparsers(help='commands')

    confname_help = 'A user-defined name to identify different configurations.'

    parser_setup = subparsers.add_parser('setup', help='Create or rewrite a configuration.')
    parser_setup.add_argument('confname', help=confname_help)
    parser_setup.add_argument('mp_type', help='A supported mediaplayer type.') #should use choices here
    parser_setup.add_argument('mp_db_path', help='The path of the mediaplayer database file.')
    parser_setup.set_defaults(func=setup)


    parser_act = subparsers.add_parser('run', help='Run a service for some configuration.')
    parser_act.add_argument('confname', help=confname_help)
    parser_act.add_argument('--port', default=9000, type=int, help='The port to run on. (default: %(default)s)')
    parser_act.set_defaults(func=run)

    args = parser.parse_args()
    args.func(args)


"""
        self._config_dir = 
        
        self._change_file = self._config_dir + os.sep + 'last_change'


        id_db_loc = self._config_dir + os.sep + 'gmids.db'
"""

if __name__ == '__main__':
    main()
