# dcache-pyclient
Python client for user interaction with dCache. Currently under development, usage only advised for (beta) testing.

A Python implementation of [ADA](https://github.com/sara-nl/SpiderScripts) (Advanced dCache API) to manage data in a [dCache storage system](https://dcache.org/) through the dCache API and WebDAV door.



## Prerequisites

- [Installation](https://github.com/sara-nl/dcache-pyclient/blob/main/docs/installation.md)
- [Configuration](https://github.com/sara-nl/dcache-pyclient/blob/main/docs/configuration.md)


## Usage

### Using ADA as a Python package
Examples:
```
from ada import AdaClient

with AdaClient(api="https://...", tokenfile="/path/to/token") as client:
    files = client.list("/pnfs/data/mydir")
    client.stage("/pnfs/data/mydir/file.dat", lifetime="7D")
    info = client.whoami()
```


### Using ADA as a Command Line Interface tool
For more information abpout how to use ADA CLI:
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