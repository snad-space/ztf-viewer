#!/bin/bash

set -e

DIR=$(dirname "$0")
curl -o"$DIR/ztf_viewer/catalogs/snad/data/snad_catalog.csv" https://snad.space/catalog/snad_catalog.csv
