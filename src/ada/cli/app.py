"""
ADA Command Line Interface application
"""
import argparse

from ada.exceptions import AdaValidationError
from ada.utils import get_version
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
    upload,
    download,
    viewtoken,
    space,
    quota,
    setlabel,
    rmlabel,
    lslabel,
    findlabel,
    setxattr,
    rmxattr,
    lsxattr,
    findxattr,
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

    auth_group = parser.add_mutually_exclusive_group()
    auth_group.add_argument(
        "--tokenfile",
        type=str,
        help="Path to tokenfile."
    )
    auth_group.add_argument(
        "--token",
        action="store_true",
        help="Use token authentication, reading the token from $BEARER_TOKEN."
    )
    auth_group.add_argument(
        "--netrcfile",
        type=str,
        help="Path to netrc file."
    )
    auth_group.add_argument(
        "--netrc",
        action="store_true",
        help="Use netrc-based password authentication, reading from ~/.netrc."
    )
    auth_group.add_argument(
        "--proxyfile",
        type=str,
        help="Path to X.509 proxy file."
    )
    auth_group.add_argument(
        "--proxy",
        action="store_true",
        help="Use X.509 proxy authentication, reading from $X509_USER_PROXY "
             "or /tmp/x509up_u<uid>."
    )

    parser.add_argument(
        "--no-igtf",
        help="Disable IGTF Grid CA certificate verification "
             "(only relevant for --proxy/--proxyfile authentication).",
        action="store_true")

    parser.add_argument(
        "--api",
        type=str,
        help="The dCache API URL to talk to."
    )

    parser.add_argument(
        "--no-verify",
        help="Disable SSL verification. Do not use in production, connection may be insecure!",
        action="store_true")

    parser.add_argument(
        "--debug",
        help="Run in debug mode (not yet implemented).",
        action="store_true")

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {get_version()}")

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

    # upload
    parser_upload = subparsers.add_parser(
        'upload',
        help="Upload a local file to dCache."
    )
    parser_upload.set_defaults(func=upload)
    parser_upload.add_argument(
        'local',
        type=str,
        help="Path of the local file to upload.",
    )
    parser_upload.add_argument(
        'remote',
        type=str,
        help="Destination path in dCache, or a directory to upload into "
             "(keeping the local filename). May be prefixed with a WebDAV "
             "door, e.g. 'https://webdav.example.org/pnfs/...', to skip "
             "door discovery.",
    )
    parser_upload.add_argument(
        "--verify-checksum",
        help="Verify the upload's checksum. Adds an MD5 checksum to the "
             "upload so dCache can verify it server-side, and removes the "
             "file automatically if it doesn't match. If the target "
             "already exists, compares checksums instead of failing.",
        action="store_true")
    parser_upload.add_argument(
        "--allow-insecure-redirects",
        help="Allow following WebDAV redirects that downgrade from HTTPS "
             "to plain HTTP. By default such redirects are refused.",
        action="store_true")

    # download
    parser_download = subparsers.add_parser(
        'download',
        help="Download a file from dCache."
    )
    parser_download.set_defaults(func=download)
    parser_download.add_argument(
        'remote',
        type=str,
        help="Path of the remote file in dCache to download. May be "
             "prefixed with a WebDAV door, e.g. "
             "'https://webdav.example.org/pnfs/...', to skip door discovery.",
    )
    parser_download.add_argument(
        'local',
        type=str,
        help="Destination local path, or a directory to download into "
             "(keeping the remote filename).",
    )
    parser_download.add_argument(
        "--verify-checksum",
        help="Verify the downloaded file's checksum against dCache's. If "
             "the target already exists locally, compares checksums "
             "instead of failing.",
        action="store_true")
    parser_download.add_argument(
        "--allow-insecure-redirects",
        help="Allow following WebDAV redirects that downgrade from HTTPS "
             "to plain HTTP. By default such redirects are refused.",
        action="store_true")

    # viewtoken
    parser_viewtoken = subparsers.add_parser(
        'viewtoken',
        help="Decode and show the properties of the current token."
    )
    parser_viewtoken.set_defaults(func=viewtoken)
    parser_viewtoken.add_argument(
        "--minimal",
        help="Show only minimal information: skip the token source, "
             "and the macaroon IP caveat check.",
        action="store_true")

    # space
    parser_space = subparsers.add_parser(
        'space',
        help="Show pool group names, or space usage for a pool group."
    )
    parser_space.set_defaults(func=space)
    parser_space.add_argument(
        'poolgroup',
        nargs="?",
        type=str,
        help="Pool group to show space usage for, or a dCache path "
             "(starting with '/') to look up the pool group(s) serving "
             "that path. If omitted, lists all pool group names.",
    )

    # quota
    parser_quota = subparsers.add_parser(
        'quota',
        help="Show storage quotas (tape/custodial and disk/replica), for user and group."
    )
    parser_quota.set_defaults(func=quota)

    # setlabel
    parser_setlabel = subparsers.add_parser(
        'setlabel',
        help="Attach a label to a file."
    )
    parser_setlabel.set_defaults(func=setlabel)
    parser_setlabel.add_argument(
        'path',
        type=str,
        help="Path to the file.",
    )
    parser_setlabel.add_argument(
        'label',
        type=str,
        help="Label to attach.",
    )

    # rmlabel
    parser_rmlabel = subparsers.add_parser(
        'rmlabel',
        help="Remove one label, or all labels, from a file."
    )
    parser_rmlabel.set_defaults(func=rmlabel)
    parser_rmlabel.add_argument(
        'path',
        type=str,
        help="Path to the file.",
    )
    # group mutual exclusive
    group = parser_rmlabel.add_mutually_exclusive_group()
    group.add_argument(
        'label',
        nargs="?",
        type=str,
        help="Label to remove. Either label or --all must be given.",
    )
    group.add_argument(
        '--all',
        help="Remove all labels from the file.",
        action="store_true")

    # lslabel
    parser_lslabel = subparsers.add_parser(
        'lslabel',
        help="List labels of a file, or check whether it has a specific label."
    )
    parser_lslabel.set_defaults(func=lslabel)
    parser_lslabel.add_argument(
        'path',
        type=str,
        help="Path to the file.",
    )
    parser_lslabel.add_argument(
        'label',
        nargs="?",
        type=str,
        help="If given, only check for this specific label.",
    )

    # findlabel
    parser_findlabel = subparsers.add_parser(
        'findlabel',
        help="Find files in a directory whose labels match a regex pattern."
    )
    parser_findlabel.set_defaults(func=findlabel)
    parser_findlabel.add_argument(
        'path',
        type=str,
        help="Directory to search.",
    )
    parser_findlabel.add_argument(
        'regex',
        type=str,
        help="Regular expression to match against labels.",
    )
    parser_findlabel.add_argument(
        "--recursive",
        help="Also search subdirectories.",
        action="store_true")

    # setxattr
    parser_setxattr = subparsers.add_parser(
        'setxattr',
        help="Set extended attributes on a file."
    )
    parser_setxattr.set_defaults(func=setxattr)
    parser_setxattr.add_argument(
        'path',
        type=str,
        help="Path to the file.",
    )
    parser_setxattr.add_argument(
        'attributes_file',
        nargs="?",
        type=str,
        help="File containing the attributes, or '-' (or omit) to read "
             "from stdin. Attributes are key=value pairs (one per line, "
             "comma-, or tab-separated), or a JSON object.",
    )

    # rmxattr
    parser_rmxattr = subparsers.add_parser(
        'rmxattr',
        help="Remove one extended attribute, or all, from a file."
    )
    parser_rmxattr.set_defaults(func=rmxattr)
    parser_rmxattr.add_argument(
        'path',
        type=str,
        help="Path to the file.",
    )
    # group mutual exclusive
    group = parser_rmxattr.add_mutually_exclusive_group()
    group.add_argument(
        'key',
        nargs="?",
        type=str,
        help="Attribute key to remove. Either key or --all must be given.",
    )
    group.add_argument(
        '--all',
        help="Remove all extended attributes from the file.",
        action="store_true")

    # lsxattr
    parser_lsxattr = subparsers.add_parser(
        'lsxattr',
        help="List extended attributes of a file, or check a specific key."
    )
    parser_lsxattr.set_defaults(func=lsxattr)
    parser_lsxattr.add_argument(
        'path',
        type=str,
        help="Path to the file.",
    )
    parser_lsxattr.add_argument(
        'key',
        nargs="?",
        type=str,
        help="If given, only check for this specific attribute key.",
    )

    # findxattr
    parser_findxattr = subparsers.add_parser(
        'findxattr',
        help="Find files in a directory whose extended attributes match a regex."
    )
    parser_findxattr.set_defaults(func=findxattr)
    parser_findxattr.add_argument(
        'path',
        type=str,
        help="Directory to search.",
    )
    # group mutual exclusive
    group = parser_findxattr.add_mutually_exclusive_group()
    group.add_argument(
        'key',
        nargs="?",
        type=str,
        help="Attribute key to match. Either key or --all must be given.",
    )
    group.add_argument(
        '--all',
        help="Search all attribute keys.",
        action="store_true")
    parser_findxattr.add_argument(
        'regex',
        type=str,
        help="Regular expression to match against attribute value(s).",
    )
    parser_findxattr.add_argument(
        "--recursive",
        help="Also search subdirectories.",
        action="store_true")

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
