# dcache-pyclient
Python client for user interaction with dCache. Currently under development. 

### Background
A Python implementation of [ADA](https://github.com/sara-nl/SpiderScripts) (Advanced dCache API) to manage data in a [dCache storage system](https://dcache.org/) through the dCache API and WebDAV door.

### Installation
To install the `dcache-pyclient` source code for development, first clone this repository and then use [Poetry](https://python-poetry.org/docs/) to install. Poetry is a tool for dependency managing and packaging in Python. If you don't have Poetry, install it first with `pipx install poetry`.
```
git clone https://github.com/sara-nl/dcache-pyclient.git
cd dcache-client
poetry install --with test
```
Note that Poetry will create a virtual environment if it is not running within an activated virtual environment already. In that case, you will need to run `poetry run` before your commands to execute them within the Poetry virtual environment.

If you prefer not to use Poetry, then you can install `dcache-pyclient` with:
```
pip install -U -e .
pip install pytest
```

### Testing
To run tests:
```
pytest tests
```
