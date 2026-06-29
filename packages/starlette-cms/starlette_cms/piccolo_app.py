"""
Piccolo AppConfig for starlette-cms.

This module is imported by ``piccolo_conf.py`` files in deployer projects and
by the ``piccolo`` CLI when running migrations.

Usage in a deployer project's ``piccolo_conf.py``::

    from piccolo.conf.apps import AppRegistry
    APP_REGISTRY = AppRegistry(apps=["starlette_cms.piccolo_app"])
"""

import pathlib

from piccolo.conf.apps import AppConfig

from starlette_cms.tables import CMSDocument, CMSMeta, CMSWebhook

APP_CONFIG = AppConfig(
    app_name="starlette_cms",
    migrations_folder_path=pathlib.Path(__file__).parent / "piccolo_migrations",
    table_classes=[CMSDocument, CMSMeta, CMSWebhook],
)
