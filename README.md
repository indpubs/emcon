# emcon — Emergency Lighting Control

A simple interface to DALI emergency lighting, using
[python-dali](https://github.com/sde1000/python-dali).

Generates plain text reports from the command line, or emails HTML
formatted reports.

Can issue some basic emergency lighting control commands (Inhibit,
Rest, Reset, Start Function Test, Start Duration Test and Stop Test)
from the command line, targetted at a single device, a whole DALI bus
or a whole site.

Currently assumes the DALI bus is connected via
[daliserver](https://github.com/onitake/daliserver), but should be
simple to adapt to other interfaces if necessary.

Configuration is in [TOML](https://toml.io/). An abbreviated example:

```
[haymakers]

name = "Haymakers"
email-to = ["steve@assorted.org.uk"]
email-from = "Fire Safety <steve@assorted.org.uk>"

[haymakers.buses]

main.hostname = "icarus.haymakers.i.individualpubs.co.uk"
main.port = 55825

[[haymakers.gear]]
bus = "main"
address = 4
name = "Public bar entrance (exit sign)"

[[haymakers.gear]]
bus = "main"
address = 6
name = "Gents urinals"

[[haymakers.gear]]
bus = "main"
address = 9
name = "Cellar stairs"
```

## Installation

First ensure [poetry](https://python-poetry.org/) is installed, then
clone this repository.

Run `poetry install` to install the various dependencies.

## Basic usage

Check all sites with a verbose report:

```
poetry run emcon -v check
```

Inhibit emergency lighting on a whole bus at a site:

```
poetry run emcon inhibit haymakers/main
```

Start a duration test on a particular emergency unit:

```
poetry run emcon start-duration-test haymakers/main/4
```

Send reports by email:
```
poetry run emcon email
```
