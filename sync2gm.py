import argparse
import appdirs
import os

import sqlite3

from sync2gm import service

def setup(args):

    service.init_config(args.confname, args.mp_type, args.mp_db_path)
    print "attached."

def run(args):
    service.start_service(args.confname, args.port, args.email, args.password)

def stop(args): 
    service.stop_service(args.port)

def status(args):
    print service.is_service_running(args.port)

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
    parser_act.add_argument('email', help="Gmail address to authenticate with.")
    parser_act.add_argument('password', help="Account password.")
    parser_act.add_argument('--port', default=9000, type=int, help='The port to run on. (default: %(default)s)')
    parser_act.set_defaults(func=run)

    parser_stop = subparsers.add_parser('stop', help='Stop a currently running service.')

    parser_stop.add_argument('--port', default=9000, type=int, help='The port the service is running on (default: %(default)s)')
    parser_stop.set_defaults(func=stop)

    parser_status = subparsers.add_parser('status', help='Display "True" if the service is running.')

    parser_status.add_argument('--port', default=9000, type=int, help='The port the service is running on (default: %(default)s)')
    parser_status.set_defaults(func=status)



    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
