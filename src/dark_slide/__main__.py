"""`python -m dark_slide` -- the same CLI as the `dark-slide` script."""

import sys

from .cli import main

sys.exit(main())
