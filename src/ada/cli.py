"""
ADA Command Line Interface
"""
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

    subparsers = parser.add_subparsers(
        help='Put commands and their arguments at the end, after the options. ADA supports these commands:')

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

    # mkdir
    parser_mkdir = subparsers.add_parser(
        'mkdir',  
        help="Create a directory.\n"
	        "To recursively create a directory and ALL of its \n"
	        "parents, add --recursive. For safety, the maximum number\n"
	        "of directories that can be created at once is 10."    
    )
    parser_mkdir.set_defaults(func=mkdir)
    parser_mkdir.add_argument(
        'path',
        type=str
    )
    parser_mkdir.add_argument(
        "--recursive",
        help="recursive",
        action="store_true")

    # delete
    parser_delete = subparsers.add_parser(
        'delete',  
        help="Delete a file or directory.\n"
	        "To recursively delete a directory and ALL of its\n"
	        "contents, add --recursive. You will need to confirm\n"
	        "deletion of each subdir, unless you add --force.\n"
	        "Please note, that dCache storage systems usually\n"
	        "don't have an undelete option.\n"
	        "Deleting a file will also delete its metadata\n"
	        "(labels and extended attributes)."
    )
    parser_delete.set_defaults(func=delete)
    parser_delete.add_argument(
        'path',
        type=str
    )
    parser_delete.add_argument(
        "--recursive",
        help="recursive",
        action="store_true")
    parser_delete.add_argument(
        "--force",
        help="force",
        action="store_true")

    # mv
    parser_mv = subparsers.add_parser(
        'mv',
        help="Rename or move a file or directory.\n"
	        "Please note, that moving a file will not change its\n"
	        "properties. A tape file will remain a tape file,\n"
	        "even when you move it to a disk directory."
    )
    parser_mv.set_defaults(func=mv)
    parser_mv.add_argument(
        'source',
        type=str
    )
    parser_mv.add_argument(
        'destination',
        type=str
    )

    # checksum
    parser_checksum = subparsers.add_parser(
        'checksum',  
        help='Show MD5/Adler32 checksums for a file, files in directory, or files in a file-list',
    )
    parser_checksum.set_defaults(func=checksum)
    parser_checksum.add_argument(
        "--recursive",
        help="recursive",
        action="store_true")
    # group mutual exclusive
    group =  parser_checksum.add_mutually_exclusive_group()
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
        debug=parsed_args.debug,    # TODO: debug option does not work
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
            with open(parsed_args.from_file, encoding="utf-8") as f:
                paths = f.read().strip().splitlines()
        elif parsed_args.path:
            paths = [parsed_args.path]
        else:
            raise argparse.ArgumentTypeError("Provide a PATH or --from-file.")
        results = client.longlist(paths)

        for line in format_longlist(results):
            print(line)


def mkdir(parsed_args) -> None:
    """Create a directory."""

    with get_client(parsed_args) as client:
        result = client.mkdir(parsed_args.path, recursive=parsed_args.recursive)
        print(result)


def delete(parsed_args) -> None:
    """Delete a file or directory."""

    with get_client(parsed_args) as client:
        client.delete(parsed_args.path, recursive=parsed_args.recursive, force=parsed_args.force)
        print(f"Deleted: {parsed_args.path}")

def mv(parsed_args) -> None:
    """Move or rename a file or directory."""

    with get_client(parsed_args) as client:
        result = client.mv(parsed_args.source, parsed_args.destination)
        print(result)

def checksum(parsed_args) -> None:
    """Get MD5/Adler32 checksums for file(s)."""

    if not parsed_args.path and not parsed_args.from_file:
        raise argparse.ArgumentTypeError("Provide a PATH or --from-file.")

    with get_client(parsed_args) as client:
        checksums = client.checksum(
            paths=parsed_args.path or [],
            recursive=parsed_args.recursive, # TODO: recursive option does not work
            from_file=parsed_args.from_file,
        )
        for cs in checksums:
            print(f"{cs.value}  {cs.path}  ({cs.checksum_type})")


def main():
    """Main program to parse commandline arguments"""

    arg_parser = parse_args()
    args = arg_parser.parse_args()

    if hasattr(args, 'func'):
        args.func(args)
    else:
        print("ERROR. Please specify a command. See --help for more information.")


if __name__ == "__main__":
    main()
