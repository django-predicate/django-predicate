import datetime

from django.db import models
from nose.tools import nottest


@nottest
class TestObj(models.Model):
    char_value = models.CharField(max_length=100, default='')
    int_value = models.IntegerField(default=0)
    date_value = models.DateField(default=datetime.date.today)
    parent = models.ForeignKey('self', related_name='children', null=True)

