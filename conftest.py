"""Root conftest — prevents pytest from collecting the plugin's __init__.py
as a test module. The plugin's __init__.py uses relative imports because
Hermes loads it via importlib spec_from_file_location, not as a package
on sys.path; pytest can't resolve those relative imports."""

collect_ignore = ["__init__.py"]
collect_ignore_glob = ["server/*", "scripts/*"]
