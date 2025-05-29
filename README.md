# SNAD ZTF DR web viewer

This projects contains a source of [ZTF](http://ztf.caltech.edu) Data Releases light curve viewer developed by [the SNAD team](http://snad.space).

## Evaluation

 Both production and development versions can be started via [Docker compose](https://docs.docker.com/compose/) using `docker-compose.yml` and `docker-compose.dev.yml` correspondingly.
 Current production configuration assumes that there is a Docker `proxy` network shared with [`jwilder/nginx-proxy`](https://github.com/nginx-proxy/nginx-proxy) which proxies the webserver to the outer world.
 Also, this configuration requires `secret.env` file containing secret environment variables, such as API keys.

### Environment variables

Environment variables to configure the server, see default values in `config.py`:
- `CACHE_TYPE`: cache type, specify `redis` to use [redis](https://redis.io) server, or `memory` to use in-process cache
- `UNAVAILABLE_CATALOGS_CACHE_TYPE`: unavailable catalog cache type, specify `redis` to use [redis](https://redis.io) server, or `memory` to use in-process cache
- `REDIS_URL`: redis server address
- `LC_API_URL`: SNAD ZTF database API address
- `AKB_API_URL`: knowledge database address
- `FEATURES_API_URL`: feature extraction service address
- `OGLE_III_API_URL`: SNAD OGLE III mirror address
- `ZTF_PERIODIC_API_URL`: SNAD mirror of the ZTF periodic variables catalog
- `TNS_API_URL`: SNAD mirror of the TNS
- `ZTF_FITS_PROXY_URL`: address of SNAD proxy for ZTF FITS
- `JS9_URL`: address of full-functional JS9 viewer supporting `JS9.LoadProxy`

### Running development docker-compose

You could run a development version of the server at `http://127.0.0.1:8050` using `docker-compose.dev.yml` file:

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

This will run Dash/Flask server in debug mode and will reload the server on code changes if you mount the source code directory `ztf_viewer` as a volume:

```sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.dev.local.yml up --build
```

### Running without docker

The server can be run locally without Docker in debug mode.

```sh
# Configure Python virtual environment
python3 -m venv ~/.virtualenv/ztf-viewer
source ~/.virtualenv/ztf-viewer/bin/activate

# Install the package
python -m pip install -e .

# Run webserver
CACHE_TYPE="memory" UNAVAILABLE_CATALOGS_CACHE_TYPE="memory" python -m ztf_viewer
```

Go to the url specified in the command line output, it should be something like http://localhost:8050/
Some features like FITS viewer wouldn't work.

## Web-services used by the viewer

- [SNAD catalog](https://snad.space/catalog)
- [SNAD ZTF DR API](http://db.ztf.snad.space) gives HTTP access to SNAD [ClickHouse](//cliclhouse.tech) installation of ZTF DR light curve database. Source code: https://github.com/snad-space/snad-ztf-db
- [SNAD Light-curve feature API](http://features.lc.snad.space/help) is a HTTP service to extract light-curve features using [`light-curve-feature`](//crates.io/crates/light-curve-feature) Rust crate. Source code: https://github.com/snad-space/web-light-curve-features
- [SNAD OGLE-III metadata API](http://ogle3.snad.space/) provides cone search within [OGLE-III variable star catalog](http://ogledb.astrouw.edu.pl/~ogle/CVS/). Source code: https://github.com/snad-space/snad-ogle3
- [SNAD ZTF Periodic Catalog API](http://periodic.ztf.snad.space) provides cone search within [ZTF Catalog of Periodic Variable Stars](http://variables.cn:88/ztf/). Source code: https://github.com/snad-space/ztf-periodic-catalog-db
- [SNAD Transient Name Server API](http://tns.snad.space) provides cone search within [TNS](https://www.wis-tns.org). Source code: https://github.com/snad-space/snad-tns
- [SNAD ZTF FITS Proxy](http://fits.ztf.snad.space/products/) is a FITS image service used by the embedded JS9 FITS viewer. Source code: https://github.com/snad-space/ztf-fits-proxy
- SNAD Anomaly Knowledge Base is an internal database for experts. Source code: https://github.com/snad-space/akb-backend
- [NASA/IPAC Infrared Science Archive](https://irsa.ipac.caltech.edu/frontpage/) is a original source of ZTF FITS files
- [Vizier](https://vizier.u-strasbg.fr) is used to access various catalogs
- [Simbad](http://simbad.u-strasbg.fr) is used for both cone search and identifier queries
- [Astrocats](https://astrocats.space) are used for cone search
- [Astro-Colibri](https://astro-colibri.science) is used for multi-messenger events code search


## Citation

Please cite our paper as well as papers describing the data you accessed through the Viewer

```bibtex
@ARTICLE{2023PASP..135b4503M,
       author = {{Malanchev}, Konstantin and {Kornilov}, Matwey V. and {Pruzhinskaya}, Maria V. and {Ishida}, Emille E.~O. and {Aleo}, Patrick D. and {Korolev}, Vladimir S. and {Lavrukhina}, Anastasia and {Russeil}, Etienne and {Sreejith}, Sreevarsha and {Volnova}, Alina A. and {Voloshina}, Anastasiya and {Krone-Martins}, Alberto},
        title = "{The SNAD Viewer: Everything You Want to Know about Your Favorite ZTF Object}",
      journal = {\pasp},
     keywords = {Variable stars, Astronomy software, Open source software, Publicly available software, Astronomy web services, 1761, 1855, 1866, 1864, 1856, Astrophysics - Instrumentation and Methods for Astrophysics},
         year = 2023,
        month = feb,
       volume = {135},
       number = {1044},
          eid = {024503},
        pages = {024503},
          doi = {10.1088/1538-3873/acb292},
archivePrefix = {arXiv},
       eprint = {2211.07605},
 primaryClass = {astro-ph.IM},
       adsurl = {https://ui.adsabs.harvard.edu/abs/2023PASP..135b4503M},
      adsnote = {Provided by the SAO/NASA Astrophysics Data System}
}
```
