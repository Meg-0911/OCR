"""Canonical CSV/XLSX projections of saved alignment rows."""
import csv
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from .alignment_review import export_text, rich_text
from .file_io import replace_file

EXPORT_COLUMNS = ['img_id', 'sentence_id', 'SinoNom_Char', 'ChuQN_txt']


def prepared_rows(rows, reviewed_only=False):
    result = []
    for row in rows:
        if row.get('duplicate_of') or row.get('review_state') == 'excluded':
            continue
        if reviewed_only and not row.get('reviewed'):
            continue
        colors = row.get('review_colors', {})
        source, source_colors = export_text(row['source'], 'source', colors.get('source'))
        target, target_colors = export_text(row['target'], 'target', colors.get('target'))
        if source and target:
            result.append((row, source, source_colors, target, target_colors))
    return result


def write_alignment(path, prepared):
    temporary = path.with_name(path.name + '.tmp')
    values = [(row['sentence_id'].rsplit('.', 1)[0] + '.jpg', row['sentence_id'], source, target)
              for row, source, _, target, _ in prepared]
    if path.suffix == '.csv':
        with temporary.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(EXPORT_COLUMNS)
            writer.writerows(values)
    else:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'Alignment'
        sheet.append(EXPORT_COLUMNS)
        for cell in sheet[1]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='234D42')
        for value, (_, source, source_colors, target, target_colors) in zip(values, prepared):
            sheet.append(value)
            for cell in sheet[sheet.max_row]:
                cell.data_type = 's'
            sheet.cell(sheet.max_row, 3).value = rich_text(source, source_colors)
            sheet.cell(sheet.max_row, 4).value = rich_text(target, target_colors)
        for column, width in zip('ABCD', (45, 48, 65, 85)):
            sheet.column_dimensions[column].width = width
        sheet.freeze_panes = 'A2'
        workbook.save(temporary)
        workbook.close()
    replace_file(temporary, path)
