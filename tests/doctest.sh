#!/bin/sh

# NOTE:
# The following commands fail due to a bug (?) in doctest:
# $ python3 -m doctest fac/__main__.py
# $ python3 -m doctest fac
# Therefore, we use the more convoluted code below to actually run the doctests.

python -c "import doctest; import fac.__main__; doctest.testmod(fac.__main__, verbose=False)"
