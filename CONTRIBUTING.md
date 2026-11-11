# Contributing

## Docstrings

The [API reference](https://sara-nl.github.io/dcache-pyclient/ada.html) is
generated from the docstrings with Sphinx (autodoc + napoleon). Docstrings
are written in English, in
[Google style](https://www.sphinx-doc.org/en/master/usage/extensions/napoleon.html).

### Guidelines

- Start with a one-line summary in the imperative ("List a directory.",
  not "Lists a directory."), followed by a blank line and more detail
  where needed.
- Write for someone using ADA as a library, who knows dCache but not this
  code. Briefly explain dCache terms where they matter (pinning, pool
  group, custodial/replica) and mention units (bytes, seconds).
- Document parameters under `Args:`, the return value under `Returns:`
  and the exceptions a caller can expect under `Raises:`. Leave out
  sections that don't apply.
- Don't repeat types in the text: they are taken from the type hints.
- Add an `Example::` section where it helps to see how something is
  used. Examples are shown as code, not run, because they need a dCache
  instance; keep them short and realistic.
- The CLI modules (`ada.cli`) are not part of the API reference; the CLI
  is documented by `ada-cli --help`.

### Template

```python
def stage(
    self,
    paths: Optional[str | list[str]] = None,
    recursive: bool = False,
    lifetime: str = "7D",
    from_file: Optional[str] = None,
) -> BulkRequest:
    """Stage files from tape, so they are online (on disk) to be read.

    Staging also pins the files: dCache keeps the online copy at least
    until the pin lifetime has passed. Give either ``paths`` or
    ``from_file``.

    Args:
        paths: dCache path, or list of paths, of the files or
            directories to stage.
        recursive: For directories, also stage the files in their
            subdirectories.
        lifetime: How long the files stay pinned, as a number with a
            unit: S, M, H or D, e.g. "12H" or "7D".
        from_file: Local file with one dCache path per line.

    Returns:
        The bulk request that dCache created for the staging.

    Raises:
        AdaTokenPermissionError: If the token does not allow staging.
        AdaValidationError: If the lifetime is not valid, or both or
            neither of ``paths`` and ``from_file`` are given.

    Example::

        with AdaClient(tokenfile="token.conf") as client:
            request = client.stage("/pnfs/data/run1/file.dat", lifetime="2D")
            print(request.request_id)
    """
```

### Checking your changes

Build the documentation locally, the same way the documentation workflow
does (needs `pip install sphinx sphinx_rtd_theme myst_parser`):

```
scripts/build_docs.sh          # result in docs/build/html/index.html
scripts/build_docs.sh -n       # also warn about broken references
```

When a change is meant to only improve documentation, check that no code
changed. This compares the code in `src/ada` with a git ref, ignoring
docstrings, comments and formatting:

```
python scripts/check_docs_only.py main
```
