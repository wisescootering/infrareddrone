# IRDrone command line tools (no GUI): synchronization, alignment, ODM exports.
#
#   docker build -t irdrone .
#   docker run --rm -it -v /path/to/FLY_test:/home/samples/FLY_test irdrone
#
# Then, inside the container (python is the IRDrone environment):
#   python synchronization/synchro_by_aruco.py --folder /home/samples/FLY_test/Synchro/ --vis "*.DNG" --nir "*.RAW"
#   python run.py --config /home/samples/FLY_test/config.json --clean-proxy --odm-multispectral --selection best-mapping
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
# rawtherapee provides rawtherapee-cli (DNG development), exiftool the metadata.
# The other libraries are needed to import OpenCV and Qt, even without a display.
RUN apt-get update && apt-get install -y --no-install-recommends \
        rawtherapee libimage-exiftool-perl ca-certificates \
        libgl1 libegl1 libglib2.0-0 libxkbcommon0 libfontconfig1 libdbus-1-3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    QT_QPA_PLATFORM=offscreen \
    MPLBACKEND=Agg \
    PYTHONUNBUFFERED=1

# Dependencies first: this layer is reused while only the code changes.
COPY requirements.txt /irdrone/requirements.txt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv --python 3.12 /opt/venv \
    && uv pip install -r /irdrone/requirements.txt

WORKDIR /irdrone
COPY . .

CMD ["/bin/bash"]
