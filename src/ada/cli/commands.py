"""
ADA CLI commands
"""
from __future__ import annotations

import os

from ada.auth import check_ip_caveat
from ada.client import AdaClient
from ada.exceptions import AdaNotFoundError, AdaValidationError
from ada.cli.formatters import format_longlist, format_quota, format_space, format_space_groups


def whoami(parsed_args) -> None:
    """Show the authenticated user's identity."""

    with __get_client__(parsed_args) as client:
        info = client.whoami()
        print(f"API:      {client.config.api}")
        versions = client.dcache_versions()
        if versions:
            print(f"Version:  {', '.join(versions)}")
        print(f"Auth:     {client.auth.describe()}")
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


def list_cmd(parsed_args) -> None:
    """List files in a directory."""

    with __get_client__(parsed_args) as client:
        for item in client.list(parsed_args.path):
            print(item)


def longlist(parsed_args) -> None:
    """List file(s) or directory with details (size, date, QoS, locality)."""

    with __get_client__(parsed_args) as client:
        results = client.longlist(parsed_args.path, from_file=parsed_args.from_file)
        for line in format_longlist(results):
            print(line)


def mkdir(parsed_args) -> None:
    """Create a directory."""

    with __get_client__(parsed_args) as client:
        result = client.mkdir(parsed_args.path, recursive=parsed_args.recursive)
        print(result)


def delete(parsed_args) -> None:
    """Delete a file or directory."""

    with __get_client__(parsed_args) as client:
        client.delete(parsed_args.path, recursive=parsed_args.recursive, force=parsed_args.force)
        print(f"Deleted: {parsed_args.path}")


def mv(parsed_args) -> None:
    """Move or rename a file or directory."""

    with __get_client__(parsed_args) as client:
        result = client.mv(parsed_args.source, parsed_args.destination)
        print(result)


def checksum(parsed_args) -> None:
    """Get MD5/Adler32 checksums for file(s)."""

    if not parsed_args.path and not parsed_args.from_file:
        raise AdaValidationError("Provide a PATH or --from-file.")

    with __get_client__(parsed_args) as client:
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
        raise AdaValidationError("Provide a PATH or --from-file.")

    with __get_client__(parsed_args) as client:
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
        raise AdaValidationError("Provide a PATH or --from-file.")

    with __get_client__(parsed_args) as client:
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


def upload(parsed_args) -> None:
    """Upload a local file to dCache."""

    with __get_client__(parsed_args) as client:
        result = client.upload(
            parsed_args.local,
            parsed_args.remote,
            verify_checksum=parsed_args.verify_checksum,
            allow_insecure_redirects=parsed_args.allow_insecure_redirects,
        )
        if result.status == "already-verified":
            print(f"Target '{result.remote_path}' already exists and checksum matches. Nothing to do.")
        else:
            print(f"Uploaded '{result.local_path}' to '{result.remote_path}'.")
            if result.checksum_verified:
                print("Checksum verified.")


def download(parsed_args) -> None:
    """Download a file from dCache."""

    with __get_client__(parsed_args) as client:
        result = client.download(
            parsed_args.remote,
            parsed_args.local,
            verify_checksum=parsed_args.verify_checksum,
            allow_insecure_redirects=parsed_args.allow_insecure_redirects,
        )
        if result.status == "already-verified":
            print(f"Target '{result.local_path}' already exists and checksum matches. Nothing to do.")
        else:
            print(f"Downloaded '{result.remote_path}' to '{result.local_path}'.")
            if result.checksum_verified:
                print("Checksum verified.")


def viewtoken(parsed_args) -> None:
    """Decode and display the properties of the current token.

    Purely for inspection: an expired token is shown as such, but
    doesn't turn into an error, since viewing a token's properties
    doesn't require it to still be usable.
    """

    with __get_client__(parsed_args) as client:
        if not parsed_args.minimal:
            source = getattr(client.auth, "source", None)
            if source:
                print(f"Token source: {source}")

        decoded = client.view_token()
        _print_token_properties(decoded)

        if not parsed_args.minimal:
            print(f"Status: {client.token_expiry_status()}")

        if not parsed_args.minimal and "ip" in decoded:
            print(f"IP caveat: {check_ip_caveat(decoded['ip'])}")


def _print_token_properties(properties: dict) -> None:
    for key, value in properties.items():
        print(f"  {key}: {value}")


def space(parsed_args) -> None:
    """Show pool group names, space usage for a pool group, or (given a
    path) space usage for the pool group(s) that serve that path."""

    target = parsed_args.poolgroup

    with __get_client__(parsed_args) as client:
        if target and target.startswith("/"):
            poolgroups = client.poolgroups_for_path(target)
            groups = [(name, client.space(name)) for name in poolgroups]
            for line in format_space_groups(groups):
                print(line)
            return

        if target:
            for line in format_space(client.space(target)):
                print(line)
        else:
            for name in client.space():
                print(name)


def quota(parsed_args) -> None:
    """Show storage quotas (tape/custodial and disk/replica), for user and group."""

    with __get_client__(parsed_args) as client:
        quotas = client.quota()
        if not quotas:
            print("You do not have any quota set on your user ID or primary group ID.")
            print("Tip: use 'ada-cli space <path>' to check available space in the "
                  "pool group(s) serving your data.")
            return
        for line in format_quota(quotas):
            print(line)


def setlabel(parsed_args) -> None:
    """Attach a label to a file."""

    with __get_client__(parsed_args) as client:
        result = client.set_label(parsed_args.path, parsed_args.label)
        print(result)


def rmlabel(parsed_args) -> None:
    """Remove one label, or all labels, from a file."""

    if not parsed_args.label and not parsed_args.all:
        raise AdaValidationError("Provide a LABEL or --all.")

    with __get_client__(parsed_args) as client:
        result = client.remove_label(
            parsed_args.path,
            label=parsed_args.label or "",
            all_labels=parsed_args.all,
        )
        print(result)


def lslabel(parsed_args) -> None:
    """List labels of a file, or check whether it has a specific label."""

    with __get_client__(parsed_args) as client:
        if parsed_args.label:
            result = client.list_labels(parsed_args.path, label=parsed_args.label)
            if not result:
                raise AdaNotFoundError(
                    f"File '{parsed_args.path}' does not have label '{parsed_args.label}'."
                )
            print(result[0])
        else:
            for label in sorted(client.list_labels(parsed_args.path)):
                print(label)


def findlabel(parsed_args) -> None:
    """Find files in a directory whose labels match a regex pattern."""

    with __get_client__(parsed_args) as client:
        results = client.find_label(
            parsed_args.path, parsed_args.regex, recursive=parsed_args.recursive
        )
        for path, labels in results:
            print(f"{path}\t{','.join(labels)}")


def __get_client__(parsed_args):
    """Create an AdaClient from the CLI context."""

    token = None
    if parsed_args.token:
        token = os.environ.get("BEARER_TOKEN")
        if not token:
            raise AdaValidationError(
                "--token was specified, but the $BEARER_TOKEN environment "
                "variable is not set."
            )

    netrc = parsed_args.netrcfile
    if parsed_args.netrc:
        netrc = ""

    proxy = parsed_args.proxyfile
    if parsed_args.proxy:
        proxy = ""

    igtf = False if parsed_args.no_igtf else None

    return AdaClient(
        api=parsed_args.api,
        token=token,
        tokenfile=parsed_args.tokenfile,
        netrc=netrc,
        proxy=proxy,
        igtf=igtf,
        verify=(not parsed_args.no_verify),
        debug=parsed_args.debug,    # TODO: debug option does not work
    )
