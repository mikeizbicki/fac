FROM debian:12-slim

# Update package list and install dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    wget \
    tar \
    make \
    && rm -rf /var/lib/apt/lists/*

# Download and install Cram
RUN wget https://bitheap.org/cram/cram-0.8.tar.gz \
    && tar zxvf cram-0.8.tar.gz \
    && cd cram-0.8 \
    && make install \
    && cd .. \
    && rm -rf cram-0.8 cram-0.8.tar.gz

# Set working directory
WORKDIR /workspace

# Default command
CMD ["/bin/bash"]
