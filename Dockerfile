FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt update
RUN apt -yq install sudo git python3-pip
RUN apt-get update && apt-get -y install libgl1
RUN pip3 install opencv-contrib-python-headless
RUN pip install --upgrade scikit-image
RUN pip install matplotlib piexif exifread requests openpyxl pandas numba
RUN pip install numpy==1.21
RUN apt-get update

RUN apt-get update && \
    apt-get -y install sudo && \
    apt-get install software-properties-common -y && \
    add-apt-repository ppa:dhor/myway && \
    apt-get update && \
    apt-get install rawtherapee -y && \
    apt-get clean && \
    useradd -d /home/rawtherapee -m rawtherapee && \
    mkdir -p /home/rawtherapee/.local/share

RUN apt-get update
RUN sudo apt install libimage-exiftool-perl -y

COPY . .

ENTRYPOINT /bin/bash

