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

# Minimal frozen TeX Live 2025 for matplotlib's pgf backend
FROM python:3.14-slim-bookworm AS texlive
ARG TL_REPO=https://ftp.tu-chemnitz.de/pub/tug/historic/systems/texlive/2025/tlnet-final
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates perl xz-utils libfontconfig1 \
    && mkdir /install-tl \
    && curl -L ${TL_REPO}/install-tl-unx.tar.gz | tar -xz --strip-components=1 -C /install-tl \
    && printf '%s\n' \
        'selected_scheme scheme-infraonly' \
        'TEXDIR /opt/texlive' \
        'TEXMFLOCAL /opt/texlive/texmf-local' \
        'TEXMFSYSCONFIG /opt/texlive/texmf-config' \
        'TEXMFSYSVAR /opt/texlive/texmf-var' \
        'tlpdbopt_install_docfiles 0' \
        'tlpdbopt_install_srcfiles 0' \
        'tlpdbopt_autobackup 0' \
        > /install-tl/texlive.profile \
    && /install-tl/install-tl --profile=/install-tl/texlive.profile --repository=${TL_REPO} \
    && ln -s /opt/texlive/bin/*-linux /opt/texlive/bin/linux
ENV PATH="/opt/texlive/bin/linux:$PATH"
RUN echo "main_memory = 50000000" >> /opt/texlive/texmf.cnf \
    && tlmgr install xetex fontspec pgf hyperref geometry underscore amsfonts \
    && fmtutil-sys --byfmt xelatex

FROM python:3.14-slim-bookworm

ENV TZ=Europe/Paris
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY --from=js9 /app/ztf_viewer/static/js9 /app/ztf_viewer/static/js9

RUN apt-get update \
    && apt-get install -y --no-install-recommends libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=texlive /opt/texlive /opt/texlive
ENV PATH="/opt/texlive/bin/linux:$PATH"

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
