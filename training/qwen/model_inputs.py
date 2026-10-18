"""Input-only clip metadata; labels and annotation evidence never enter the prompt."""
from pathlib import Path


def clip_prompt(record, default):
    if record.get('schema') != 'clip_binary_v1':
        return default
    category = record['category_definition']
    if category['id'] != record['category_id']:
        raise ValueError('Category snapshot mismatch')
    return ('Кадры одного короткого фрагмента кассовой операции даны по порядку. '
            'Проверь только указанную категорию по видимым действиям. '
            f'Категория: {category["label"]}. '
            f'Признаки события: {category["required"]}. '
            f'Похожий допустимый вариант: {category["normal"]}. '
            'Верни только JSON: {"verdict":"violation"}, если видны признаки этой категории, '
            'или {"verdict":"no_violation"}, если показан допустимый вариант для этой категории. '
            'Это оценка выбранного признака, а не юридическое заключение или оценка всего видео. '
            'Не делай выводов о личности людей или невидимых операциях в банковской системе.')


def frame_paths(record, default_root):
    root = Path(record.get('frame_root', default_root)).resolve()
    explicit_root = 'frame_root' in record
    result = []
    for frame in record['frames']:
        path = (root / frame['path']).resolve()
        # Existing scanner supplies absolute paths; new dataset paths are bounded.
        if explicit_root and not path.is_relative_to(root):
            raise ValueError('Frame path escapes frame_root')
        result.append(path)
    return result
