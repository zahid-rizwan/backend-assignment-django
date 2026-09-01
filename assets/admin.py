from django.contrib import admin
from .models import Asset, Employee, CheckOut, OverdueNotice

admin.site.register(Asset)
admin.site.register(Employee)
admin.site.register(CheckOut)
admin.site.register(OverdueNotice)