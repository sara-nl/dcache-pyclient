"""
ADA CLI commands
"""
from __future__ import annotations

from ada.client import AdaClient
from ada.exceptions import AdaValidationError
from ada.cli.formatters import format_longlist


def whoami(parsed_args) -> None:
    """Show the authenticated user's identity."""

    with __get_client__(parsed_args) as client:
        info = client.whoami()
        print(f"API:      {client.config.api}")
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


def space(parsed_args) -> None:
    """Show pool group names, space usage for a pool group, or (given a
    path) space usage for the pool group(s) that serve that path."""

    target = parsed_args.poolgroup

    with __get_client__(parsed_args) as client:
        if target and target.startswith("/"):
            poolgroups = client.poolgroups_for_path(target)
            for i, name in enumerate(poolgroups):
                if i > 0:
                    print()
                print(f"[{name}]")
                _print_space(client.space(name))
            return

        if target:
            _print_space(client.space(target))
        else:
            for name in client.space():
                print(name)


def _print_space(result) -> None:
    print(f"Total:     {result.total}")
    print(f"Free:      {result.free}")
    print(f"Precious:  {result.precious}")
    print(f"Removable: {result.removable}")
    print(f"Available: {result.free + result.removable}  (free + removable)")


def __get_client__(parsed_args):
    """Create an AdaClient from the CLI context."""

    return AdaClient(
        api=parsed_args.api,
        tokenfile=parsed_args.tokenfile,
        verify=(not parsed_args.no_verify),
        debug=parsed_args.debug,    # TODO: debug option does not work
    )
