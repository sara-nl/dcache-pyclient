# dcache-pyclient
A Python client for user interaction with a [dCache](https://dcache.org/) instance to manage data through the REST API and WebDAV door.
This tool is a Python implementation of the [ADA](https://github.com/sara-nl/SpiderScripts) (Advanced dCache API)  bash script.

**_Disclaimer:_**  Currently under development, usage only advised for (beta) testing.


## Documentation
If you want to use a released version of dcache-pyclient, find the instructions in the [documentation](https://sara-nl.github.io/dcache-pyclient).


## Development
If you want to install an unreleased version, develop, or test locally, you can download the `dcache-pyclient` source code by cloning this repository:
```
git clone https://github.com/sara-nl/dcache-pyclient.git
cd dcache-pyclient
```

### Install with Poetry
If you plan to publish the package, we recommend using [Poetry](https://python-poetry.org/docs/) to install, build, and distribute the package. Poetry is a tool for dependency managing and packaging in Python. If you don't have Poetry, install it first with `pipx install poetry`.
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

To perform the integration tests, that actually interact with a dCache instance, you need to create a json file with the
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

### Build documentation
The documentation is generated automatically with [Sphinx](https://www.sphinx-doc.org) and Github Actions, see the [workflow](.github/workflows/documentation.yml). If you want to build the documentation locally, run:

```
pip install sphinx sphinx_rtd_theme myst_parser
sphinx-apidoc -o docs/source src/ada
sphinx-build -M html docs/source docs/build   
```
This will create html files in `docs/build/html`. 