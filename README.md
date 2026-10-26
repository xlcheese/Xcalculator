# Xcalculator

A calculator for Linux Mint and the Cinnamon desktop, made in the style of the
Mint X-Apps: a classic menubar, the system theme, and nothing that looks out of
place next to Xed or Xviewer.

![Scientific mode](screenshots/scientific.png)

## Modes

Choose a mode from the **Mode** menu (or Ctrl+Alt and the mode's first letter).

- **Basic**: everyday sums
- **Scientific**: powers, roots, trigonometry, logarithms, factorials, combinations and a menu of more functions
- **Financial**: loans and savings (N, I/Y, PV, PMT, FV), cash flows (NPV, IRR) and depreciation
- **Programmer**: HEX, DEC, OCT and BIN, word sizes from 8 to 64 bits, and bitwise operators
- **Unit Converter**: twelve categories, converted as you type

Every answer goes into a history you can click to reuse. The history can be
printed like an adding-machine tape. With `python3-mpmath` installed, answers
can have up to 50 decimal places.

Press **F1** in the app for the documentation, and **Ctrl+F1** for the keyboard
shortcuts.

| Basic | Programmer | Unit Converter |
|---|---|---|
| ![Basic](screenshots/basic.png) | ![Programmer](screenshots/programmer.png) | ![Unit Converter](screenshots/unit-converter.png) |

## Install

Download the `.deb` from the [latest release](https://github.com/xlcheese/Xcalculator/releases/latest)
and open it, or install it from a terminal:

```
sudo apt install ./xcalculator_0.9_all.deb
```

Xcalculator then appears in the menu under **Accessories**.

To run it without installing, you need Python 3 and GTK 3 (both come with Linux
Mint):

```
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 python3-mpmath
python3 usr/lib/xcalculator/xcalculator.py
```

`python3-gi-cairo` is needed for printing, and `python3-mpmath` for more than
15 decimal places. Xcalculator still runs without them.

## Build the package

```
sudo apt install debhelper
dpkg-buildpackage -us -uc -b
```

The package is written to the folder above this one.

## License

Copyright © 2026 Wesley Hayslip

Xcalculator is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version. See [LICENSE](LICENSE).

Developed with the help of Claude, an AI assistant by Anthropic.
