"""Reconcile concurrent field edits against the client's saved base revision."""


def merge_rows(base, incoming, current):
    missing = object()
    old = {row['id']: row for row in base}
    local = {row['id']: row for row in incoming}
    remote = {row['id']: row for row in current}
    result = {key: dict(row) for key, row in remote.items()}
    for key, row in local.items():
        before, saved = old.get(key), remote.get(key)
        if before is None:
            if saved is not None and saved != row:
                raise ValueError('ID cặp mới trùng với một cặp đã lưu.')
            result[key] = row
            continue
        changes = {field: row.get(field, missing) for field in row.keys() | before.keys()
                   if row.get(field, missing) != before.get(field, missing)}
        if saved is None:
            if changes:
                raise ValueError('Cặp đang sửa đã bị xóa ở phiên khác.')
            continue
        for field, value in changes.items():
            if saved.get(field, missing) != before.get(field, missing) and saved.get(field, missing) != value:
                raise ValueError(f"{row['sentence_id']}: {field} đã được sửa ở phiên khác.")
            if value is missing:
                result[key].pop(field, None)
            else:
                result[key][field] = value
    for key, before in old.items():
        if key in local:
            continue
        saved = remote.get(key)
        if saved is not None and saved != before:
            raise ValueError(f"{before['sentence_id']}: không thể xóa cặp đã có chỉnh sửa mới.")
        result.pop(key, None)
    shared = set(old) & set(local) & set(remote)
    order = lambda rows: [row['id'] for row in rows if row['id'] in shared]
    reordered = order(base) != order(incoming)
    if reordered and order(current) not in (order(base), order(incoming)):
        raise ValueError('Thứ tự cặp đã được đổi ở hai phiên. Giữ bản đã lưu để đối chiếu.')
    ordered = incoming if reordered else current
    keys = list(dict.fromkeys([row['id'] for row in ordered] + [row['id'] for row in incoming] + list(result)))
    return [result[key] for key in keys if key in result]
