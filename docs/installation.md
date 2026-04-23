# Installation

## Requirements

- Python 3.10 or higher
- Dependency on [`httpx`](https://www.python-httpx.org/) - HTTP client that supports sync/async requests
- Access to a dCache instance with a valid API endpoint
- Authentication credentials (token, netrc, or X.509 proxy)


## Install from source

To install the `dcache-pyclient` source code, you first need to clone this repository:
```
git clone https://github.com/sara-nl/dcache-pyclient.git
cd dcache-pyclient
```

We recommend working in a virtual environment. You can create one with:
```
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

### Install with Poetry
If you are a developer, we recommend using [Poetry](https://python-poetry.org/docs/) to install, build, and distribute the package. Poetry is a tool for dependency managing and packaging in Python. If you don't have Poetry, install it first with `pipx install poetry`.
```
poetry install --with test
```
Note that Poetry will create a virtual environment if it is not running within an activated virtual environment already. In that case, you will need to run `poetry run` before your commands to execute them within the Poetry virtual environment.


### Install with Pip
If you prefer not to use Poetry, then you can install `dcache-pyclient` with:
```
pip install -U -e .
pip install pytest
```

### Test installation

To perform the unit tests, run:
```
pytest tests/unit
```

To perform the integration tests, that interact with a dCache instance, you need to create a json file with the
following information (see `tests/env.json` for a template):
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
pytest tests/integration --target-env tests/env.json -v
```

This will run integration tests for both the ADA CLI and library. You can also run them separately with:

```
pytest tests/integration/test_cli.py --target-env tests/env.json -v
pytest tests/integration/test_library.py --target-env tests/env.json -v
```

## Install package from PyPI
The latest release of dcache-pyclient can be installed as a package from PyPI with:
```
pip install dcache-pyclient
```

Check the installation of the CLI application:
```
ada-cli --help
```
