# brain.wav

This instruction is for running the project.

## Install and Setup

### Python Setup

Create and activate virtual env:

    $ python3 -m venv .venv

    $ source .venv/bin/activate


Install dependencies:


    $ pip install -r requirements.txt

### Chuck

Linux:

    $ sudo apt install chuck

MacOS:

    $ brew install chuck

Windows:

    $ https://chuck.stanford.edu

### REAPER/ICST

MacOS:

    $ brew install reaper

Windows and Linux:

    $ https://reaper.fm

ICST:

    $ https://ambisonics.ch

### Audio Loopback Driver (>= 53 channels)

MacOS:

    $ brew install --cask blackhole-64ch

Windows:

    $ ASIO Driver

Linux:

    $ JACK/Pipewire

## Running the Project

1. Run REAPER `spatialization/main.RPP` with the ICST plugins 

2. Run ChucK


    $ cd synth && chuck -c53 --driver:JACK main.ck # --driver:JACK on Linux 

3. Run Python


    $ cd ui && python3 main.py