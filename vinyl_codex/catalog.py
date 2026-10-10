from .safety import SafeError, museum_id, no_links, inside


def discover(config, selected_id):
    selected_id = museum_id(selected_id)
    no_links(config.archive)
    if not config.archive.is_dir():
        raise SafeError("Архив отсутствует или недоступен.")
    matches = []
    for path in config.archive.iterdir():
        if path.name.startswith(selected_id + " - ") and path.name[len(selected_id)+3:]:
            no_links(path)
            path = inside(path, config.archive)
            if path.is_dir():
                matches.append(path)
    if len(matches) != 1:
        raise SafeError("Папка Museum ID не найдена или соответствие неоднозначно.")
    return matches[0]
