# SNAD ZTF DR web viewer

This projects contains a source of [ZTF](http://ztf.caltech.edu) Data Releases light curve viewer developed by [the SNAD team](http://snad.space).

## Evaluation

 Both production and development versions can be started via [Docker compose](https://docs.docker.com/compose/) using `docker-compose.yml` and `docker-compose-dev.yml` correspondingly.
 Current configurations assumes that there is a Docker `proxy` network shared with [`jwilder/nginx-proxy`](https://github.com/jwilder/nginx-proxy) which proxies the webserver to the outer world.
 Also this configuration require `secret.env` file containing secret environment variables, such as API keys. 

### Environment variables

- `CACHE_TYPE`: cache type, specify `redis` to use [redis](https://redis.io) server, or `memory` to use in-process cache
- `REDIS_URL`: redis server address
- `LC_API_URL`: light curve API address
- `PRODUCTS_URL`: address of ZTF DR FITS data-products 
- `TNS_API_URL`: transient name server address, use `https://sandbox-tns.weizmann.ac.il/` for tests
- `TNS_API_KEY`: transient name server bot API key

### Running without docker

The server can be run locally without Docker in debug mode.

```sh
# Configure Python virtual environment
python3 -m venv ~/.venv/ztf-viewer
source ~/.venv/ztf-viewer/bin/activate

# Install dependencies
pip3 install -r requirements.txt

# Run webserver
CACHE_TYPE="memory" TNS_API_URL="" python3 main.py
```

Go to the url specified in the command line output, it should be something like http://localhost:8050/
Some features like FITS viewer and TNS cross-match wouldn't work.
