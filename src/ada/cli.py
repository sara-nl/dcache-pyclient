"""
ADA Command Line Interface
"""
import argparse

from ada.client import AdaClient
from ada.formatters import format_longlist
from ada.exceptions import AdaValidationError

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
        help="Path to tokenfile."
    )

    parser.add_argument(
        "--api",
        type=str,
        help="The dCache API URL to talk to."
    )

    parser.add_argument(
        "--debug",
        help="Run in debug mode (not yet implemented).",
        action="store_true")

    subparsers = parser.add_subparsers(
        help='ADA supports these commands (put commands and their arguments at the end, after the options):')

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
        type=str,
        help='Path of file or directory to list.'
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
        help='Path of file or directory to longlist.'
    )
    group.add_argument(
        '--from-file',
        type=str,
        help='File containing list of files or directories to longlist.'
    )

    # mkdir
    parser_mkdir = subparsers.add_parser(
        'mkdir',  
        help="Create a directory."
    )
    parser_mkdir.set_defaults(func=mkdir)
    parser_mkdir.add_argument(
        'path',
        type=str
    )
    parser_mkdir.add_argument(
        "--recursive",
        help="Recursively create a directory.\n"
	        "For safety, the maximum number\n"
	        "of directories that can be created is 10."    ,
        action="store_true")

    # delete
    parser_delete = subparsers.add_parser(
        'delete',  
        help="Delete a file or directory."
    )
    parser_delete.set_defaults(func=delete)
    parser_delete.add_argument(
        'path',
        help="Path to file or directory to delete.",
        type=str
    )
    parser_delete.add_argument(
        "--recursive",
        help="Recursively delete directories. You will need to confirm\n"
	        "deletion of each subdir, unless you add --force.",
        action="store_true")
    parser_delete.add_argument(
        "--force",
        help="Force recursive deletion of directories.",
        action="store_true")

    # mv
    parser_mv = subparsers.add_parser(
        'mv',
        help="Rename or move a file or directory.\n"
	        "Note that moving a file will not change its\n"
	        "properties. A tape file will remain on tape,\n"
	        "even when you move it to a disk directory."
    )
    parser_mv.set_defaults(func=mv)
    parser_mv.add_argument(
        'source',
        type=str,
        help="Original path/filename.",
    )
    parser_mv.add_argument(
        'destination',
        type=str,
        help="New path/filename.",
    )

    # checksum
    parser_checksum = subparsers.add_parser(
        'checksum',  
        help='Show MD5/Adler32 checksums for a file, files in directory, or files listed in a file.',
    )
    parser_checksum.set_defaults(func=checksum)
    parser_checksum.add_argument(
        "--recursive",
        help="Recursively get checksums (not yet implemented).",
        action="store_true")
    # group mutual exclusive
    group =  parser_checksum.add_mutually_exclusive_group()
    group.add_argument(
        'path',
        nargs="?",
        type=str,
        help="Path to file or directory to show checksums for.",
    )
    group.add_argument(
        '--from-file',
        type=str,
        help='File containing list of files or directories to show checksums for.'
    )

    # stage
    parser_stage = subparsers.add_parser(
        'stage',  
        help="Stage/pin a file from tape (bring to disk/online)."
    )
    parser_stage.set_defaults(func=stage)
    parser_stage.add_argument(
        "--recursive",
        help="Recursively stage files.",
        action="store_true")
    parser_stage.add_argument(
        "--lifetime",
        help="Pin lifetime duration in units of\n"
	        "S, M, H, or D; standing for seconds,\n"
	        "minutes, hours, and days. Default is 7D.",          
        type=str,
        default="7D"
    )
    # group mutual exclusive
    group =  parser_stage.add_mutually_exclusive_group()
    group.add_argument(
        'path',
        nargs="?",
        type=str,
        help="Path to file or directory for stage. Either path or --from-file must be given.",
    )
    group.add_argument(
        '--from-file',  
        type=str,
        help='File containing list of files or directories to stage.'
    )

    # unstage
    parser_unstage = subparsers.add_parser(
        'unstage',  
        help="Unstage/unpin file so dCache may purge its online replica."
    )
    parser_unstage.set_defaults(func=unstage)
    parser_unstage.add_argument(
        "--recursive",
        help="Recursively unstage files.",
        action="store_true")
    parser_unstage.add_argument(
        "--request-id",
        type=str,
        help="If --request-id is given, release only the associated pin; by default all pins are released.",
    )
    # group mutual exclusive
    group =  parser_unstage.add_mutually_exclusive_group()
    group.add_argument(
        'path',
        nargs="?",
        type=str,
        help="Path to file or directory for unstage. Either path or --from-file must be given.",
    )
    group.add_argument(
        '--from-file',  
        type=str,
        help='File containing list of files or directories to unstage.'
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
        results = client.longlist(parsed_args.path, from_file=parsed_args.from_file)
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
            paths=parsed_args.path,
            recursive=parsed_args.recursive,
            from_file=parsed_args.from_file,
        )
        for cs in checksums:
            print(f"{cs.value}  {cs.path}  ({cs.checksum_type})")


def stage(parsed_args) -> None:
    """Bring files from tape to disk (stage/pin)."""

    if not parsed_args.path and not parsed_args.from_file:
        raise argparse.ArgumentTypeError("Provide a PATH or --from-file.")

    with get_client(parsed_args) as client:
        result = client.stage(
            paths=parsed_args.path,
            recursive=parsed_args.recursive,
            lifetime=parsed_args.lifetime,
            from_file=parsed_args.from_file,
        )
        print(f"Stage request submitted: {result.request_id}")
        if result.request_url:
            print(f"Request URL: {result.request_url}")
        print(f"Targets: {len(result.targets)} file(s)")


def unstage(parsed_args) -> None:
    """Release file(s) from disk so dCache may purge their online replica (unstage/unpin)."""

    if not parsed_args.path and not parsed_args.from_file:
        raise argparse.ArgumentTypeError("Provide a PATH or --from-file.")

    with get_client(parsed_args) as client:
        result = client.unstage(
            paths=parsed_args.path,
            recursive=parsed_args.recursive,
            request_id=parsed_args.request_id,
            from_file=parsed_args.from_file,
        )
        print(f"Unstage request submitted: {result.request_id}")
        if result.request_url:
            print(f"Request URL: {result.request_url}")
        print(f"Targets: {len(result.targets)} file(s)")


def main():
    """Main program to parse commandline arguments"""

    arg_parser = parse_args()
    args = arg_parser.parse_args()

    if hasattr(args, 'func'):
        args.func(args)
    else:
        raise AdaValidationError("ERROR. Please specify a command. See --help for more information.")


if __name__ == "__main__":
    main()
