"""python -m everstickynote で起動する入口（PyInstaller もここから作る）。"""

from everstickynote.main import main

raise SystemExit(main())
