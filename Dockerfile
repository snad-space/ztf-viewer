FROM python:3.10-bullseye

# Timezone settings
ENV TZ=Europe/Moscow
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Install gunicorn to run a web-server
RUN pip install gunicorn

# Install JS9 for FITS viewer
ARG JS9_VERSION=3.8
RUN curl -LJ -o js9.tar.gz https://github.com/ericmandel/js9/archive/v${JS9_VERSION}.tar.gz \
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

# Install Python build deps for ARM64:
# healpy: cfitsio
# confluence-kafka: z, ssl, sasl2, zstd, rdkafka
RUN [ $(arch) = "x86_64" ] \
    || ( \
        apt-get update \
        && apt-get install -y --no-install-recommends libcfitsio-dev libz-dev libssl-dev libsasl2-dev libzstd-dev \
        && rm -rf /var/lib/apt/lists/* \
        && curl -LOJ https://github.com/edenhill/librdkafka/archive/refs/tags/v1.9.2.tar.gz \
        && tar -xzvf librdkafka-1.9.2.tar.gz \
        && rm librdkafka-1.9.2.tar.gz \
        && cd /librdkafka-1.9.2 \
        && ./configure --prefix=/usr \
        && make \
        && make install \
        && cd / \
        && rm -rf /librdkafka-1.9.2 \
        && ldconfig \
    )

# Install dependencies
COPY requirements.txt /app/
RUN pip install -r /app/requirements.txt

# Configure and download dustmaps
RUN echo '{"data_dir": "/dustmaps"}' > /dustmapsrc
ENV DUSTMAPS_CONFIG_FNAME /dustmapsrc
RUN python -c 'from dustmaps import sfd, bayestar; sfd.fetch(); bayestar.fetch()'

EXPOSE 80

ENV PYTHONUNBUFFERED TRUE

COPY pyproject.toml setup.py MANIFEST.in /app/
COPY ztf_viewer /app/ztf_viewer/
ARG GITHUB_SHA
RUN if [ -z ${GITHUB_SHA+x} ]; then echo "$GITHUB_SHA is not set"; else echo "github_sha = \"${GITHUB_SHA}\"" >> /app/ztf_viewer/_version.py; fi
RUN pip install /app

ENTRYPOINT ["gunicorn", "-w4", "-t300", "-b0.0.0.0:80", "ztf_viewer.__main__:server()"]
