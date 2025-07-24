#!/bin/sh

set -ex

IMG=0ad/img
PDF=0ad/pdf

mkdir -p $PDF

python3 scripts/make_pdf.py $IMG/'ὁ ὁπλίτης.png' $IMG/'ἡ γυνή.png' -s 2 -o $PDF/units.pdf

python3 scripts/make_pdf.py $IMG/'ἡ οἰκία.png' -o $PDF/buildings1.pdf -s 3 --pages=1

python3 scripts/make_pdf.py $IMG/'ἡ ἀγορὰ.png' $IMG/'ἡ ἀποθήκη.png' $IMG/'ὁ ἀγρός.png' $IMG/'ὁ πύργος.png' $IMG/'τὸ ἐμπόριον.png' $IMG/'τὸ τεῖχος.png' -o $PDF/buildings2.pdf -s 3 --pages=3

python3 scripts/make_pdf.py $IMG/'ἡ βιβλιοθήκη.png' $IMG/'ἡ σχολή.png' $IMG/'ὁ Παρθενών.png' $IMG/'τὸ γυμνάσιον.png' $IMG/'τὸ θέατρον.png' $IMG/'τὸ ἱερόν.png' -o $PDF/buildings3.pdf -s 4 --pages=2
