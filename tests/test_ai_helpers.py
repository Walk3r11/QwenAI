import json
import pytest
from ai_routes import _clamp_freshness, _extract_scan_items_for_session, _freshness_alert, _freshness_label, _parse_ai_json, _recipe_entries_from_parsed

@pytest.mark.parametrize('raw,expected', [('{"items":[]}', {'items': []}), ('```json\n{"a":1}\n```', {'a': 1})])
def test_parse_ai_json(raw, expected):
    assert _parse_ai_json(raw) == expected

def test_parse_ai_json_trailing_noise():
    raw = 'Sure — here you go:\n{"items": [{"name": "x", "freshness": 8, "qty": "1"}]}\nHope this helps!'
    out = _parse_ai_json(raw)
    assert out['items'][0]['name'] == 'x'

def test_parse_ai_json_top_level_recipe_list():
    raw = '[{"name": "Soup", "uses": ["a"], "extra": [], "steps": ["mix"], "minutes": 10}]'
    out = _parse_ai_json(raw)
    assert 'recipes' in out
    assert out['recipes'][0]['name'] == 'Soup'

def test_parse_ai_json_top_level_scan_list_without_freshness():
    raw = '[{"name": "apple", "qty": "1"}]'
    out = _parse_ai_json(raw)
    assert out.get('items') and out['items'][0]['name'] == 'apple'
    assert 'recipes' not in out or not out.get('recipes')

def test_extract_scan_items_alternate_keys_and_food_alias():
    assert _extract_scan_items_for_session({'foods': [{'food': 'Banana', 'qty': '2'}]})[0]['name'] == 'Banana'
    assert _extract_scan_items_for_session({'data': {'detected_items': [{'product': 'Milk', 'freshness': 8}]}})[0]['name'] == 'Milk'

def test_extract_scan_items_misrouted_recipes_array():
    parsed = {'recipes': [{'name': 'Tomato', 'qty': '3', 'freshness': 7}]}
    rows = _extract_scan_items_for_session(parsed)
    assert len(rows) == 1 and rows[0]['name'] == 'Tomato'

def test_recipe_entries_alternate_keys():
    assert len(_recipe_entries_from_parsed({'Recipes': [{'name': 'A', 'uses': []}]})) == 1
    assert _recipe_entries_from_parsed({'recipe': {'name': 'B', 'steps': ['x']}})[0]['name'] == 'B'
    assert _recipe_entries_from_parsed({'data': {'recipes': [{'name': 'C'}]}})[0]['name'] == 'C'

def test_clamp_freshness():
    assert _clamp_freshness(3) == 3
    assert _clamp_freshness(0) == 1
    assert _clamp_freshness(15) == 5
    assert _clamp_freshness('4') == 4
    assert _clamp_freshness(None) == 3

def test_freshness_alert():
    assert _freshness_alert(5) is None
    assert 'soon' in (_freshness_alert(4) or '').lower()
    assert 'soon' in (_freshness_alert(3) or '').lower()
    assert 'WARNING' in (_freshness_alert(2) or '')
    assert 'SPOILED' in (_freshness_alert(1) or '')

def test_freshness_label():
    assert _freshness_label(5.0) == 'fresh'
    assert _freshness_label(4.0) == 'good'
    assert _freshness_label(3.0) == 'use-soon'