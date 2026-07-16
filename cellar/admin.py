from django.contrib import admin

from .models import Bottle, Producer, TastingNote, Vintage, Wine


class WineInline(admin.TabularInline):
    model = Wine
    extra = 0


class VintageInline(admin.TabularInline):
    model = Vintage
    extra = 0


class BottleInline(admin.TabularInline):
    model = Bottle
    extra = 0


class TastingNoteInline(admin.TabularInline):
    model = TastingNote
    extra = 0


@admin.register(Producer)
class ProducerAdmin(admin.ModelAdmin):
    list_display = ["name", "region", "country"]
    list_filter = ["country"]
    search_fields = ["name", "region"]
    inlines = [WineInline]


@admin.register(Wine)
class WineAdmin(admin.ModelAdmin):
    list_display = ["name", "producer", "wine_type", "varietals", "appellation"]
    list_filter = ["wine_type", "producer"]
    search_fields = ["name", "producer__name", "varietals", "appellation"]
    inlines = [VintageInline]


@admin.register(Vintage)
class VintageAdmin(admin.ModelAdmin):
    list_display = ["wine", "year", "drink_from", "drink_until", "window_status"]
    list_filter = ["wine__wine_type"]
    search_fields = ["wine__name", "wine__producer__name"]
    inlines = [BottleInline, TastingNoteInline]


@admin.register(Bottle)
class BottleAdmin(admin.ModelAdmin):
    list_display = ["vintage", "size", "status", "purchase_date", "purchase_price", "location"]
    list_filter = ["status", "size"]
    search_fields = ["vintage__wine__name", "vintage__wine__producer__name", "location"]
    date_hierarchy = "purchase_date"


@admin.register(TastingNote)
class TastingNoteAdmin(admin.ModelAdmin):
    list_display = ["vintage", "author", "tasted_date", "rating"]
    list_filter = ["author", "rating"]
    search_fields = ["vintage__wine__name", "notes"]
    date_hierarchy = "tasted_date"
