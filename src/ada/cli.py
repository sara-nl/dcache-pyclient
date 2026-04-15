import sys
import argparse

from ada.client import AdaClient
from ada.formatters import format_longlist

def parse_args() -> argparse.ArgumentParser:
    """
    Define argument parser for the ADA Command Line Interface
    """

    parser = argparse.ArgumentParser(
        description=(
            "ADA (Advanced dCache API) command line interface\n"
            "to manage your data in dCache."
        )
    )

    parser.add_argument(
        "--tokenfile",
        type=str,
        help="Path to tokenfile",
        required=True
    )

    parser.add_argument(
        "--api",
        type=str,
        help="The dCache API URL to talk to",
        required=True        
    )

    parser.add_argument(
        "--debug",
        help="run in debug mode",
        action="store_true")

    subparsers = parser.add_subparsers(help='ADA supports these commands')

    # whoami
    parser_whoami = subparsers.add_parser(
        'whoami',
        help='Show how dCache identifies you.',
    )
    parser_whoami.set_defaults(func=whoami)

    # list
    parser_list = subparsers.add_parser(
        'list',  
        help='List files in a directory.',    
    )
    parser_list.set_defaults(func=list_cmd)
    parser_list.add_argument(
        'path',
        type=str
    )
    
    # longlist
    parser_longlist = subparsers.add_parser(
        'longlist',  
        help='List a file or directory with details.',    
    )
    parser_longlist.set_defaults(func=longlist)

    # group mutual exclusive
    group =  parser_longlist.add_mutually_exclusive_group()
    group.add_argument(
        'path',
        nargs="?",
        type=str,  
    )
    group.add_argument(
        '--from-file',
        type=str
    )

    return parser



def get_client(parsed_args):
    """Create an AdaClient from the CLI context."""

    return AdaClient(
        api=parsed_args.api,
        tokenfile=parsed_args.tokenfile,
        debug=parsed_args.debug,
    )

# Commands

def whoami(parsed_args) -> None:
    """Show the authenticated user's identity."""

    with get_client(parsed_args) as client:
        info = client.whoami()
        print(f"Status:   {info.status}")
        if info.username:
            print(f"Username: {info.username}")
        if info.uid is not None:
            print(f"UID:      {info.uid}")
        if info.gids:
            print(f"GIDs:     {', '.join(str(g) for g in info.gids)}")
        if info.home:
            print(f"Home:     {info.home}")
        if info.root:
            print(f"Root:     {info.root}")
        # Show dCache version if available
        raw = info.raw
        if "version" in raw:
            print(f"dCache:   {raw['version']}")


def list_cmd(parsed_args) -> None:
    """List files in a directory."""

    with get_client(parsed_args) as client:
        for item in client.list(parsed_args.path):
            print(item)


def longlist(parsed_args) -> None:
    """List file(s) or directory with details (size, date, QoS, locality)."""

    with get_client(parsed_args) as client:
        if parsed_args.from_file:
            paths = open(parsed_args.from_file).read().strip().splitlines()
        elif parsed_args.path:
            paths = [parsed_args.path]
        else:
            raise argparse.ArgumentTypeError("Provide a PATH or --from-file.")
        results = client.longlist(paths)
        # print(results)
        for line in format_longlist(results):
            print(line)
        # for line in results:
        #     print(line)


def main():

    arg_parser = parse_args()
    args = arg_parser.parse_args()

    if hasattr(args, 'func'):
        args.func(args)
    else:
        print("ERROR. Please specify a command. See --help for more information.")


if __name__ == "__main__":
    main()