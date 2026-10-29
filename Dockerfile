# Original repo: https://github.com/ericmandel/js9
FROM python:3.14-slim-bookworm AS js9
ARG JS9_VERSION=3.9
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gcc libc6-dev make \
    && curl -LJ -o js9.tar.gz https://github.com/js9-software/js9/archive/v${JS9_VERSION}.tar.gz \
    && tar -xzvf js9.tar.gz \
    && cd js9-${JS9_VERSION} \
    && ./configure --with-webdir=/app/ztf_viewer/static/js9 \
    && make \
    && make install

FROM python:3.14-slim-bookworm

ENV TZ=Europe/Paris
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY --from=js9 /app/ztf_viewer/static/js9 /app/ztf_viewer/static/js9

RUN apt-get update \
    && apt-get install -y --no-install-recommends texlive-xetex texlive-latex-recommended texlive-pictures fonts-lmodern \
    && rm -rf /var/lib/apt/lists/* /usr/share/doc/* \
    && echo "main_memory = 50000000" > /etc/texmf/texmf.d/10main_memory.cnf \
    && update-texmf \
    && fmtutil-sys --byfmt xelatex

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.12.11 /uv /uvx /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1

# Install dependencies, but not the project itself yet, so this layer stays cached
# across source changes
COPY pyproject.toml uv.lock /app/
RUN uv sync --project /app --locked --no-install-project

EXPOSE 80

ENV PYTHONUNBUFFERED TRUE

COPY ztf_viewer /app/ztf_viewer/
ARG GITHUB_SHA
RUN if [ -z ${GITHUB_SHA+x} ]; then echo "$GITHUB_SHA is not set"; else echo "github_sha = \"${GITHUB_SHA}\"" >> /app/ztf_viewer/_version.py; fi
RUN uv sync --project /app --locked

ENV PATH="/app/.venv/bin:$PATH"

HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:80/health')" || exit 1

ENTRYPOINT ["uvicorn", "ztf_viewer.__main__:app.server", "--host", "0.0.0.0", "--port", "80", "--workers", "1", "--timeout-keep-alive", "75"]
