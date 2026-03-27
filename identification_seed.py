from sqlalchemy import select
from sqlalchemy.orm import Session
from identification_data import IDENTIFICATION_GROUPS_SEED
from models import IngredientIdentificationGroup

def ensure_identification_groups(db: Session) -> None:
    for row in IDENTIFICATION_GROUPS_SEED:
        code = str(row['code'])
        exists = db.scalar(select(IngredientIdentificationGroup.id).where(IngredientIdentificationGroup.code == code))
        if exists is None:
            db.add(IngredientIdentificationGroup(code=code, label=str(row['label']), sort_order=int(row['sort_order'])))
    db.commit()