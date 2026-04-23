"""
ADA Command Line Interface application
"""
import argparse

from ada.exceptions import AdaValidationError
from ada.cli.commands import (
    whoami,
    list_cmd,
    longlist,
    mkdir,
    delete,
    mv,
    checksum,
    stage,
    unstage,
)


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
    group = parser_longlist.add_mutually_exclusive_group()
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
             "of directories that can be created is 10.",
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
    group = parser_checksum.add_mutually_exclusive_group()
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
    group = parser_stage.add_mutually_exclusive_group()
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
    group = parser_unstage.add_mutually_exclusive_group()
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
