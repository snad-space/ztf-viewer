FROM python:3.12-bookworm

# Timezone settings
ENV TZ=Europe/Moscow
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1

# Install JS9 for FITS viewer
# Original repo: https://github.com/ericmandel/js9
ARG JS9_VERSION=3.9
RUN curl -LJ -o js9.tar.gz https://github.com/js9-software/js9/archive/v${JS9_VERSION}.tar.gz \
    && tar -xzvf js9.tar.gz \
    && cd js9-${JS9_VERSION} \
    && ./configure --with-webdir=/app/ztf_viewer/static/js9 \
    && make \
    && make install \
    && cd - \
    && rm -rf js9.tar.gz js9-${JS9_VERSION}

# Install LaTeX for downloadable figures
RUN apt-get update \
    && apt-get install -y --no-install-recommends texlive-latex-extra cm-super-minimal dvipng texlive-xetex texlive-fonts-recommended \
    && rm -rf /var/lib/apt/lists/*

# Increse latex maximum memory size - matplotlib wants it
RUN echo "main_memory = 50000000" > /etc/texmf/texmf.d/10main_memory.cnf \
    && update-texmf \
    && texhash \
    && fmtutil-sys --all || test 1

# Install Python build deps, mostly needed for ARM64
# healpy: cfitsio
# h5py: hdf5
# confluence-kafka: rdkafka
RUN apt-get update \
    && apt-get install -y --no-install-recommends libhdf5-dev libcfitsio-dev librdkafka-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies, including gunicorn (the "deploy" dependency group), but
# not the project itself yet, so this layer stays cached across source changes
COPY pyproject.toml uv.lock /app/
RUN uv sync --project /app --locked --no-install-project --group deploy

# Configure and download dustmaps
RUN echo '{"data_dir": "/dustmaps"}' > /dustmapsrc
ENV DUSTMAPS_CONFIG_FNAME /dustmapsrc
# Our copy of the best-fit-only Bayestar19 map, bayestar.fetch() is blocked by
# the Harvard Dataverse WAF, see https://github.com/gregreen/dustmaps/issues/54
ARG BAYESTAR_URL=https://sai.snad.space/tmp/viewer-files/bayestar2019-bestfit.h5
RUN uv run --project /app python -c "from dustmaps.fetch_utils import download_and_verify; \
    download_and_verify('$BAYESTAR_URL', '4dd35460f1da9bb4f4e535f25eb0c530', '/dustmaps/bayestar/bayestar2019.h5')"
RUN uv run --project /app python -c 'from dustmaps import csfd; csfd.fetch()'

EXPOSE 80

ENV PYTHONUNBUFFERED TRUE

COPY ztf_viewer /app/ztf_viewer/
ARG GITHUB_SHA
RUN if [ -z ${GITHUB_SHA+x} ]; then echo "$GITHUB_SHA is not set"; else echo "github_sha = \"${GITHUB_SHA}\"" >> /app/ztf_viewer/_version.py; fi
RUN uv sync --project /app --locked --group deploy

ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT ["gunicorn", "-w2", "--threads=8", "-t70", "--keep-alive=75", "-b0.0.0.0:80", "ztf_viewer.__main__:app"]
