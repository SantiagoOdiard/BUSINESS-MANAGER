from datetime import datetime
from pathlib import Path
import shutil

base = Path(__file__).resolve().parent
source = base / 'business.db'
backup_dir = base / 'backups'
backup_dir.mkdir(exist_ok=True)

destination = backup_dir / f'business_backup_{datetime.now():%Y%m%d_%H%M%S}.db'
shutil.copy2(source, destination)
print(f'Backup created: {destination}')
