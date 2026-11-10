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
  --tokenclient TOKENCLIENT
                        OIDC client configuration to use with oidc-agent.
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
In the examples below we assume you have a valid tokenfile. You can check if that is the case with:
```
ada-cli --tokenfile </path/to/token> viewtoken
```

Now let's try to authenticate to the dCache API with this tokenfile:
```
ada-cli --tokenfile </path/to/token> --api <URL> whoami
```

If successful, you should see something like:
```
API:      <URL>
Version:  11.2.11(11.2.11)
Auth:     token (tokenfile: tokenfile.conf)
Status:   AUTHENTICATED
Username: username
UID:      XXXXX
GIDs:     XXXXX, XXXXX
Home:     </path/to/dCache/homedir>
Root:     /
```

For convenience, we can put the tokenfile path and the API URL in ADA's configuration file so we don't need to add them on the commandline every time:
```
echo "api=<URL>"> ~/.ada/ada.conf
echo "tokenfile=</path/to/token>" >> ~/.ada/ada.conf
```

To investigate your home directory on dCache: 
```
ada-cli list </path/to/dCache/homedir>
```

Create a directory:
```
ada-cli mkdir </path/to/dCache/homedir/testdir>
```

Next, we will create a testfile and upload it to the directory we just created:
```
fallocate -x -l 1G testfile (or "mkfile 1g $testfile" on Darwin/macOS)
ada-cli upload testfile </path/to/dCache/homedir/testdir>
```

Check if the file was uploaded:
```
ada-cli list </path/to/dCache/homedir/testdir>
```

Let's move/rename the file:
```
ada-cli mv </path/to/dCache/homedir/testdir/testfile> </path/to/dCache/homedir/testdir/testfile2>
```

To delete the file:
```
ada-cli delete </path/to/dCache/homedir/testdir/testfile2>
```

Then delete the directory:
```
ada-cli delete --recursive </path/to/dCache/homedir/testdir/
```

These are some of the basic commands of `ada-cli`. More advanced examples will follow later.


## Using authentication methods

`--token`, `--tokenfile`, `--tokenclient`, `--netrc`, `--netrcfile`,  `--proxy`, and `--proxyfile`
are mutually exclusive. Use `--token` to explicitly request token
authentication from the `$BEARER_TOKEN` environment variable (the token value
itself is never passed on the command line):
```
export BEARER_TOKEN=<your-bearer-token>
ada-cli --token --api <URL> whoami
```

Use `--tokenclient` to instruct ADA to use oidc-agent with the specified client configuration.
This requires that the requested client configuration is known to oidc-agent:
```
ada-cli --tokenclient <clientConfigName> --api <URL> whoami
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