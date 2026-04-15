# dcache-pyclient
Python client for user interaction with dCache. Currently under development. 

## Background
A Python implementation of [ADA](https://github.com/sara-nl/SpiderScripts) (Advanced dCache API) to manage data in a [dCache storage system](https://dcache.org/) through the dCache API and WebDAV door.


## Installation
Currently, `dcache-pyclient` can only be installed from source. The package will be published on PyPI in a a later phase.

To install the `dcache-pyclient` source code, you first need to clone this repository:
```
git clone https://github.com/sara-nl/picasclient.git
cd picasclient
```

We recommend working in a virtual environment. You can create one with:
```
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

### Use Poetry or Pip
If you are a developer, we recommend using [Poetry](https://python-poetry.org/docs/) to install, build, and distribute the package. Poetry is a tool for dependency managing and packaging in Python. If you don't have Poetry, install it first with `pipx install poetry`.
```
poetry install --with test
```
Note that Poetry will create a virtual environment if it is not running within an activated virtual environment already. In that case, you will need to run `poetry run` before your commands to execute them within the Poetry virtual environment.

If you prefer not to use Poetry, then you can install `dcache-pyclient` with:
```
pip install -U -e .
pip install pytest
```

To perform the unit tests, run:
```
pytest tests/unit
```

To perform the integration tests, that interact with a dCache instance, you need to create a json file with the
following information (see `tests/input.json` for a template):
```
{
    "user": "user_name",
    "api": "api_url",
    "webdav": "webdav_url",
    "homedir": "user_homedir_on_dcache",    
    "testdir": "test_dirname",
    "tokenfile": "tokenfile.conf"
}
```
where `user_homedir_on_dcache` is the full path of the user's home directory on dCache; `testdir` is the directory in which test data will be written (without `user_homedir_on_dcache` in front); `tokenfile.conf` is an rclone config file that can be created with [`get-macaroon`](https://doc.spider.surfsara.nl/en/latest/Pages/storage/ada-interface.html#create-a-macaroon).

Then run:
```
pytest tests/integration --target-env tests/input.json
```

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
Examples:
```
ada --help
ada --tokenfile </path/to/token> --api <URL> whoami 
ada --tokenfile </path/to/token> --api <URL> list </pnfs/data/mydir? 
```