from backend.alignment_review import comparison_key, export_text, paint, rich_text, score, score_boxes, source_glyph, unmarked_count


def test_comparison_key_keeps_vietnamese_accents_and_drops_punctuation():
    assert comparison_key('Đoá, HOA!  Chịu?') == 'đoá hoa chịu'
    assert comparison_key('đóa') != comparison_key('đoá')
    assert comparison_key('天，地。').replace(' ', '') == '天地'


def test_partial_overrides_color_both_sides_and_score_han_characters():
    row = {
        'source': '一二', 'target': 'nhất, nhị!',
        'marks': [
            {'source_start': 0, 'source_end': 2, 'target_start': 0, 'target_end': 10, 'kind': 'match'},
            {'source_start': 1, 'source_end': 2, 'target_start': 6, 'target_end': 9, 'kind': 'mismatch'},
        ],
    }
    source_colors = paint(row['source'], row['marks'], 'source')
    target_colors = paint(row['target'], row['marks'], 'target')
    assert source_colors == ['match', 'mismatch']
    assert target_colors[6:9] == ['mismatch'] * 3
    assert unmarked_count(row['source'], source_colors, 'source') == 0
    assert str(rich_text(row['target'], target_colors)) == row['target']
    assert score([row]) == {'total': 2, 'red': 1, 'unmarked': 0, 'percent': 50.0}
    assert source_glyph('\U000f02c7')


def test_unmarked_text_defaults_to_black_and_is_ready_for_export():
    source = '天地'
    target = 'thiên địa'
    assert paint(source, [], 'source') == ['match', 'match']
    assert paint(target, [], 'target') == ['match'] * len(target)
    assert unmarked_count(source, paint(source, [], 'source'), 'source') == 0
    assert score([{'source': source, 'target': target}]) == {
        'total': 2, 'red': 0, 'unmarked': 0, 'percent': 100.0,
    }


def test_box_score_counts_per_glyph_color_without_alignment_pairs():
    assert score_boxes([{'boxes': [
        {'transcription': '天', 'review_kind': None},
        {'transcription': '地', 'review_kind': 'mismatch'},
    ]}]) == {'total': 2, 'red': 1, 'unmarked': 0, 'percent': 50.0}


def test_export_removes_punctuation_and_lowercases_vietnamese_without_losing_colors():
    source, source_colors = export_text('一， 二。', 'source', ['match'] * 2 + ['mismatch'] * 3)
    target, target_colors = export_text('NHẤT, NHỊ!', 'target', ['match'] * 6 + ['mismatch'] * 4)
    assert source == '一二'
    assert source_colors == ['match', 'mismatch']
    assert target == 'nhất nhị'
    assert target_colors == ['match'] * 4 + [None] + ['mismatch'] * 3


def test_export_preserves_quoc_ngu_whitespace_exactly():
    value = '  THIÊN,   ĐỊA!\nNGƯỜI  '
    target, colors = export_text(value, 'target', ['match'] * len(value))
    assert target == '  thiên   địa\nngười  '
    assert colors == [
        None if char.isspace() else 'match' for char in target
    ]


def test_rich_text_keeps_spaces_attached_to_a_colored_word_run():
    value = '  thiên địa  '
    colors = [None] * 2 + ['match'] * 6 + ['mismatch'] * 3 + [None] * 2
    result = rich_text(value, colors)
    assert str(result) == value
    assert [block.text for block in result] == ['  thiên', ' địa  ']
