from typing import Union

IDENTIFICATION_GROUPS_SEED: list[dict[str, Union[int, str]]] = [{'code': 'dairy', 'label': 'Dairy', 'sort_order': 10}, {'code': 'protein', 'label': 'Protein (meat, fish, eggs, tofu, legumes, etc.)', 'sort_order': 20}, {'code': 'produce', 'label': 'Produce (fresh fruits, vegetables, herbs)', 'sort_order': 30}, {'code': 'pantry', 'label': 'Pantry (packaged, canned, dried, boxed shelf-stable)', 'sort_order': 40}, {'code': 'all', 'label': 'All (general, mixed, or hard to classify)', 'sort_order': 50}]
ALLOWED_GROUP_CODES_PROMPT = ', '.join((str(g['code']) for g in IDENTIFICATION_GROUPS_SEED))
KNOWN_IDENTIFICATION_CODES = frozenset((str(g['code']) for g in IDENTIFICATION_GROUPS_SEED))
