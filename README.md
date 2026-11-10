<<<<<<< HEAD
# brain.wav

This instruction is for running the project.

## Install and Setup

=======
# sonification

This instruction is for running the project on a Ubuntu studio (debian system)

## Install and Setup

In the desktop audio settings, use KT audio and select "pro audio"

>>>>>>> main
### Python Setup

Create and activate virtual env:

    $ python3 -m venv .venv

    $ source .venv/bin/activate


Install dependencies:


    $ pip install -r requirements.txt

### SUPERCOLLIDER

MacOS: 

    https://github.com/supercollider/supercollider/releases/download/Version-3.14.1/SuperCollider-3.14.1-macOS-universal.dmg
    
Linux:

    https://github.com/supercollider/supercollider/releases/download/Version-3.14.1/SuperCollider-3.14.1-Source.tar.bz2

Windows: 

    https://github.com/supercollider/supercollider/releases/download/Version-3.14.1/SuperCollider-3.14.1_Release-x64-VS-426edf6.exe

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

2. Run SuperCollider

3. Run Python

    $ cd ui && python3 main.py
