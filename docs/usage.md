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
    whoami              Show how dCache identifies you.
    list                List files in a directory.
    longlist            List a file or directory with details.
    stat                Show complete metadata for a file or directory.
    mkdir               Create a directory.
    delete              Delete a file or directory.
    mv                  Rename or move a file or directory. Note that moving a file will not change its properties. A tape file will remain on tape,
                        even when you move it to a disk directory.
    checksum            Show MD5/Adler32 checksums for a file, files in directory, or files listed in a file.
    stage               Stage/pin a file from tape (bring to disk/online).
    unstage             Unstage/unpin file so dCache may purge its online replica.
    upload              Upload a local file to dCache.
    download            Download a file from dCache.
    viewtoken           Decode and show the properties of the current token.
    setxattr            Set extended attributes on a file.
    rmxattr             Remove one extended attribute, or all, from a file.
    lsxattr             List extended attributes of a file, or check a specific key.
    findxattr           Find files in a directory whose extended attributes match a regex.
    setlabel            Attach a label to a file.
    rmlabel             Remove one label, or all labels, from a file.
    lslabel             List labels of a file, or check whether it has a specific label.
    findlabel           Find files in a directory whose labels match a regex pattern.
    space               Show pool group names, or space usage for a pool group.
    quota               Show storage quotas (tape/custodial and disk/replica), for user and group.
```
and options:
```
  -h, --help            show this help message and exit
  --tokenfile TOKENFILE
                        Path to tokenfile.
  --token               Use token authentication, reading the token from $BEARER_TOKEN.
  --netrcfile NETRCFILE
                        Path to netrc file.
  --netrc               Use netrc-based password authentication, reading from ~/.netrc.
  --proxyfile PROXYFILE
                        Path to X.509 proxy file.
  --proxy               Use X.509 proxy authentication, reading from $X509_USER_PROXY or /tmp/x509up_u<uid>.
  --no-igtf             Disable IGTF Grid CA certificate verification (only relevant for --proxy/--proxyfile authentication).
  --api API             The dCache API URL to talk to.
  --no-verify           Disable SSL verification. Do not use in production, connection may be insecure!
  --debug               Run in debug mode (not yet implemented).
  --version             show program's version number and exit
```

To get details for a specific ADA command:
```
ada-cli <command> --help
```

### Examples
```
ada-cli --tokenfile </path/to/token> --api <URL> whoami 
ada-cli --tokenfile </path/to/token> --api <URL> list </path/to/dCache/dir>
ada-cli --tokenfile </path/to/token> --api <URL> longlist --from-file <filename>
```

### Authentication
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