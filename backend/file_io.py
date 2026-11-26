"""Atomic replacement with bounded retries for transient Windows file handles."""
import os
import time


def replace_file(temporary, target):
    for attempt in range(6):
        try:
            os.replace(temporary, target)
            return
        except PermissionError:
            if os.name != 'nt' or attempt == 5:
                raise
            time.sleep(.02 * 2 ** attempt)
