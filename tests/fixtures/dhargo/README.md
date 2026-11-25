# Dhargo class observations

The observations cover the 14 martial class files in Dhargo's public class collection, retrieved on November 24, 2026. The folder lists the class files without a redistribution notice. Each observation records the public file ID, SHA-256 of the original bytes, and the game-defined numeric and catalog choices. Original downloads stay outside this repository. [Dhargo's public folder](https://drive.google.com/drive/folders/1GNvjKwC8XU5wXPA3VMkdWFNp3efRr8wb)

The upstream oracle called `parseCustomClassDoc` in DFO revision `a3eb1605ea1dc391b691fe314377458a7e63e483` for each original document and checked the skipped-pick list. It called `difficultyPoints`, `totalAdjust`, and `advancementMultiplier` on the parsed fields. The normalized digest uses `customClassDoc` with the sample ID as its name, recursively sorted JSON keys, preserved array order, and UTF-8 compact JSON. These expectations are independent of the optimizer. Race is absent from class documents. [Pinned source adapter](https://github.com/Lattymoy/daggerfall-js-source/blob/a3eb1605ea1dc391b691fe314377458a7e63e483/src/systems/customClass.js)

The ordinary test suite rebuilds each mechanical example using its numeric skill IDs, validates it offline, and compares its exported document with the source digest. To check the exact original bytes against an installed wheel, run either command from the repository root.

```console
python tools/verify_dhargo.py --directory /path/to/downloaded/classes
python tools/verify_dhargo.py --download
```
