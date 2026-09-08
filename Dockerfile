FROM debian:13-slim

WORKDIR /fac

# install fac system dependencies
COPY packages.txt /fac
RUN apt-get update \
 && xargs -a packages.txt apt-get install -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/*

# configure git to remove warnings during tests;
# we only use dummy info here;
# "real" commits should never happen inside the container
RUN git config --global init.defaultBranch master \
 && git config --global user.email "you@example.com" \
 && git config --global user.name "Your Name"

# install fac python dependencies
COPY requirements.txt /fac
RUN pip3 install -r requirements.txt --break-system-packages

# install fac
COPY pyproject.toml /fac/
COPY fac /fac/fac/
COPY facd /fac/facd/
# ENV needed for pip3 to build successfully within the container without .git/
ENV SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0
RUN pip3 install . --break-system-packages

# copy tests
COPY docs /fac/docs/
