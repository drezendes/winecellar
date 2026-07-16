from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # iPhone photo libraries hand us HEIC; teach Pillow to open it so
        # ImageField validation and the AI image pipeline both accept it.
        from pillow_heif import register_heif_opener

        register_heif_opener()
