# Configuration

ADA configuration options can be given as in a config file, environmental variables, or (CLI/constructor) arguments. In order of precedence from high to low:

```
CLI/constructor arguments ← Environment variables ← ~/.ada/ada.conf ←  /etc/ada.conf  ← <package>/etc/ada.conf 
```

The configuration options are:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `api` | string | - | dCache REST API URL (must start with `https://` and end with `/api/v1` or `/api/v2`) |
| `channel_timeout` | integer | `3600` | Default SSE channel timeout in seconds |
| `debug` | boolean | `false` | Enable debug logging |
| `tokenfile` | string | — | Default token file path (precedence over netrcfile) |
| `netrcfile` | string | — | Default netrc file path (precedence over proxy authentification)|
| `igtf` | boolean | `true` | Use IGTF Grid certificates for proxy authentication |

Note that the order of precedence for authentication is (high-to-low):
```
token ← tokenfile ← netrcfile ← Grid proxy
```

The CLI `--token` flag does not take a value; it explicitly selects token
authentication and reads the token from the `$BEARER_TOKEN` environment
variable, raising an error if it is not set. It is mutually exclusive with
`--tokenfile`, `--netrcfile`, `--netrc`, `--proxyfile`, and `--proxy`. If none
of these is given, `$BEARER_TOKEN` is still used automatically when set (see
[Environment Variables](#environment-variables)).

The CLI `--netrc` flag does not take a value; it explicitly selects netrc-based
password authentication from `~/.netrc`. Use `--netrcfile PATH` instead to use a
different file. Either way, the file must exist and must not be world-readable
or world-writable, or an error is raised.

The CLI `--proxy` flag does not take a value; it explicitly selects X.509
proxy authentication, reading the proxy certificate from `$X509_USER_PROXY`
(or `/tmp/x509up_u<uid>` if unset). Use `--proxyfile PATH` instead to use a
different file. By default the proxy is verified against IGTF Grid CA
certificates; pass `--no-igtf` to disable this (overriding the `igtf` config
value for this run).

All of `--token`, `--tokenfile`, `--netrc`, `--netrcfile`, `--proxy`, and
`--proxyfile` are mutually exclusive with each other.

## Config File

ADA uses a simple `key=value` format, with lines starting with `#` as comments. This is compatible with the original Bash version. An example can be found in [ada.conf](https://github.com/sara-nl/dcache-pyclient/blob/main/src/ada/etc/ada.conf).

```ini
# ADA configuration
api=https://dcacheview.grid.surfsara.nl:22880/api/v1
tokenfile=tokenfile.conf
igtf=true
channel_timeout=3600
debug=false
netrcfile=~/.netrc
```

Config file location, in order of precedence from high to low, is expected to be:

| Priority | Path | Description |
|----------|------|-------------|
| 1 (highest) | `~/.ada/ada.conf` | User-level config |
| 2 | `/etc/ada.conf` | System-wide config |
| 3 (lowest) | `<package>/etc/ada.conf` | Bundled defaults |


## Environment Variables

Environment variables override config file values. They are checked after loading config files but before applying explicit CLI arguments.

| Variable | Overrides | Description |
|----------|-----------|-------------|
| `ada_api` | `api` | dCache API URL |
| `ada_debug` | `debug` | Enable debug output (`true`/`false`) |
| `ada_channel_timeout` | `channel_timeout` | SSE channel timeout |
| `ada_igtf` | `igtf` | Use IGTF certificates |
| `ada_tokenfile` | `tokenfile` (precedence over ada_netrcfile)| Token file path |
| `ada_netrcfile` | `netrcfile` | Netrc file path (precedence over X509_USER_PROXY) |
| `BEARER_TOKEN` | — | Direct bearer token string (precedence over ada_tokenfile) |
| `X509_USER_PROXY` | — | X.509 proxy file path |
| `X509_CERT_DIR` | — | Grid certificate directory |


## Example Setup

Minimal setup to avoid passing arguments every time:

```bash
# Create config directory
mkdir -p ~/.ada
chmod 700 ~/.ada

# Create config file
cat > ~/.ada/ada.conf << 'EOF'
api=https://dcacheview.grid.surfsara.nl:22880/api/v1
EOF

# Store your token
echo "your-bearer-token-here" > ~/.ada/token
chmod 600 ~/.ada/token

# Point to it in config
echo "tokenfile=$HOME/.ada/token" >> ~/.ada/ada.conf
```

Now you can use ADA without any arguments:

```bash
ada-cli whoami
ada-cli list /pnfs/grid.sara.nl/data/myproject
```

## Library Configuration

When using ADA as a library, you can also pass custom config paths (in order of high-to-low precedence):

```python
from ada.client import AdaClient

# Use default config file search
client = AdaClient()

# Use custom config paths
client = AdaClient(config_paths=["/custom/path/ada.conf"])

# Override everything explicitly (ignores config files for these values)
client = AdaClient(
    api="https://dcacheview.grid.surfsara.nl:22880/api/v1",
    tokenfile="/path/to/token",
    debug=True,
)
```

Explicit constructor arguments always have the highest priority.