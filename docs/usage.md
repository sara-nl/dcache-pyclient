# Usage

## Using ADA as a library
Examples:
```
from ada import AdaClient

with AdaClient(api="https://...", tokenfile="/path/to/token") as client:
    files = client.list("/pnfs/data/mydir")
    client.stage("/pnfs/data/mydir/file.dat", lifetime="7D")
    info = client.whoami()
```

Find a complete description of the interface in the [ADA API Reference](https://sara-nl.github.io/dcache-pyclient/ada.html).

## Using ADA as a CLI tool
For more information abpout how to use the ADA command line interface tool:
```
ada-cli --help
```
This will show the currently supported ADA commands:
```
whoami          Show how dCache identifies you.
list            List files in a directory.
longlist        List a file or directory with details.
mkdir           Create a directory.
delete          Delete a file or directory.
mv              Rename or move a file or directory. Note that moving a file will not change its properties. A tape file will remain on tape, even when you
                move it to a disk directory.
checksum        Show MD5/Adler32 checksums for a file, files in directory, or files listed in a file.
stage           Stage/pin a file from tape (bring to disk/online).
unstage         Unstage/unpin file so dCache may purge its online replica.
```
To get details for a specific ADA command:
```
ada-cli <command> --help
```

Examples:
```
ada-cli --tokenfile </path/to/token> --api <URL> whoami 
ada-cli --tokenfile </path/to/token> --api <URL> list </path/to/dCache/dir>
ada-cli --tokenfile </path/to/token> --api <URL> longlist --from-file <filename>
```

`--tokenfile`, `--token`, `--netrcfile`, `--netrc`, `--proxyfile`, and `--proxy`
are mutually exclusive. Use `--token` to explicitly request token
authentication from the `$BEARER_TOKEN` environment variable (the token value
itself is never passed on the command line):
```
export BEARER_TOKEN=<your-bearer-token>
ada-cli --token --api <URL> whoami
```

Use `--netrc` to explicitly request netrc-based password authentication from
`~/.netrc`, or `--netrcfile` to use a different file. The file must not be
world-readable or world-writable:
```
ada-cli --netrc --api <URL> whoami
ada-cli --netrcfile /path/to/netrc --api <URL> whoami
```

Use `--proxy` to explicitly request X.509 proxy authentication, reading the
proxy certificate from `$X509_USER_PROXY` (or `/tmp/x509up_u<uid>` if unset),
or `--proxyfile` to use a different file. By default the proxy is verified
against IGTF Grid CA certificates (`$X509_CERT_DIR`, or
`/etc/grid-security/certificates` if unset); add `--no-igtf` to disable this,
e.g. for a dCache instance with a regular (non-Grid) certificate:
```
ada-cli --proxy --api <URL> whoami
ada-cli --proxyfile /tmp/x509up_u1000 --api <URL> whoami
ada-cli --proxy --no-igtf --api <URL> whoami
```