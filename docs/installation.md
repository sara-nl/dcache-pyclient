# Installation

## Requirements

- Python 3.9 or higher
- Dependency on [`httpx`](https://www.python-httpx.org/) - HTTP client that supports sync/async requests
- Access to a dCache instance with a valid API endpoint
- Authentication credentials (token, netrc, or X.509 proxy)
- Transfering files to/from dCache is not (yet) implemented. We currently depend on [rclone](https://rclone.org/) for this.
- We recommend working in a virtual environment. You can create one with:
    ```
    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    ```

## Install package
The latest release of dcache-pyclient can be installed as a package from [PyPI](https://pypi.org/project/dcache-pyclient/) with:
```
pip install dcache-pyclient
```

Check the installation of the CLI application:
```
ada-cli --help
```

### Using dcache-pyclient with oidc-agent
To use dcache-pyclient with [oidc-agent](https://indigo-dc.github.io/oidc-agent/), install it with the oidc-agent extra:
```
pip install dcache-pyclient[oidc-agent]
```
The oidc-agent tool has to be installed and properly configured on the system for dcache-pyclient to be able use it. Refer to the [oidc-agent documentation](https://indigo-dc.github.io/oidc-agent/usage/oidc-gen/) on how to set up oidc-agent and configure the client. It is recommended to use the command `oidc-add myClientName` to pre-load the client configuration in oidc-agent before starting dcache-pyclient. You can re-use you oidc-agent setup for file transfers with [rclone](https://rclone.org/webdav/#openid-connect).

## For developers
If you want to modify `dcache-pyclient` or run integration tests on your dCache instance, find the source code and instructions on the [Github repo](https://github.com/sara-nl/dcache-pyclient).