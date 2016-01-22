import datetime

from django.db import models
from nose.tools import nottest


class Base(models.Model):
    class Meta:
        abstract = True
    char_value = models.CharField(max_length=100, default='')
    int_value = models.IntegerField(default=0)
    date_value = models.DateField(default=datetime.date.today)
    datetime_value = models.DateTimeField(default=datetime.datetime.now)


@nottest
class TestObj(Base):
    parent = models.ForeignKey('self', related_name='children', null=True)
    m2ms = models.ManyToManyField(
        'testapp.M2MModel', related_name='test_objs')

    @property
    def some_property(self):
        return {'x': 'y'}


class M2MModel(Base):
    pass


class OneToOneModel(Base):
    test_obj = models.OneToOneField(
        TestObj, null=True)


class CustomRelatedNameOneToOneModel(Base):
    test_obj = models.OneToOneField(
        TestObj, related_name='custom_one_to_one', null=True)


class ForeignKeyModel(Base):
    test_obj = models.ForeignKey(TestObj, null=True)
