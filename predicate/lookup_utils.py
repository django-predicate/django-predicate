import datetime
import operator

import django

import re

from django.db import models


class LookupQueryEvaluator(object):
    evaluators = ()

    def __init__(self, rhs):
        self.rhs = rhs

    def __call__(self, lhs):
        rhs = self.cast_rhs(lhs)
        lhs = self.cast_lhs(lhs)
        return all(evaluator(lhs, rhs) for evaluator in self.evaluators)

    def cast_lhs(self, lhs):
        """
        Cast lhs as needed to compare with self.rhs.

        Default to identity.
        """
        return lhs

    def cast_rhs(self, lhs):
        """
        Cast self.rhs as needed to compare with lhs.

        Default to identity.
        """
        return self.rhs


def NOT_NULL(lhs, rhs):
    return lhs is not None


class IsNull(LookupQueryEvaluator):
    evaluators = ((lambda lhs, rhs: (lhs is None) == rhs), )


class Contains(LookupQueryEvaluator):
    evaluators = (NOT_NULL, (lambda lhs, rhs: rhs in lhs))


class Regex(LookupQueryEvaluator):
    evaluators = (NOT_NULL, (lambda lhs, regex: bool(regex.search(lhs))))
    flags = 0  # No flag bits set.
    escape = False
    template = '%s'

    def __init__(self, rhs):
        if self.escape:
            rhs = re.escape(rhs)
        self.rhs = re.compile((self.template % rhs), flags=self.flags)


class StartsWith(LookupQueryEvaluator):
    evaluators = (NOT_NULL, (lambda lhs, rhs: lhs.startswith(rhs)))


class EndsWith(LookupQueryEvaluator):
    evaluators = (NOT_NULL, (lambda lhs, rhs: lhs.endswith(rhs)))


class IRegex(Regex):
    flags = re.I


class IContains(IRegex):
    escape = True


class IExact(IContains):
    template = r'^%s$'


class IStartsWith(IContains):
    template = r'^%s'


class IEndsWith(IContains, EndsWith):
    template = r'%s$'


class Exact(LookupQueryEvaluator):
    evaluators = (operator.eq, )


class In(LookupQueryEvaluator):
    evaluators = ((lambda lhs, rhs: lhs in rhs), )

    def __init__(self, rhs):
        self.rhs = {self._cast(value) for value in rhs}

    def _cast(self, value):
        if isinstance(value, tuple):
            # Handles __in=MyModel.objects.values_list('pk')
            value, = value
        elif isinstance(value, models.Model):
            value = value.pk
        return value

    def cast_lhs(self, lhs):
        return self._cast(lhs)


def is_date(obj):
    """
    Returns True if obj is a date object proper.

    This is a bit tricky because datetime inherits from date.
    """
    return isinstance(obj, datetime.date) and not isinstance(obj, datetime.datetime)


class DateCastMixin(object):
    def cast_lhs(self, lhs):
        if isinstance(lhs, datetime.datetime) and is_date(self.rhs):
            lhs = lhs.date()
        return lhs

    def cast_rhs(self, lhs):
        rhs = self.rhs
        if isinstance(rhs, datetime.datetime) and is_date(lhs):
            rhs = rhs.date()
        return rhs


class GT(DateCastMixin, LookupQueryEvaluator):
    evaluators = (NOT_NULL, operator.gt)


class GTE(DateCastMixin, LookupQueryEvaluator):
    evaluators = (NOT_NULL, operator.ge)


class LT(DateCastMixin, LookupQueryEvaluator):
    evaluators = (NOT_NULL, operator.lt)


class LTE(DateCastMixin, LookupQueryEvaluator):
    evaluators = (NOT_NULL, operator.le)


class Day(LookupQueryEvaluator):
    evaluators = (NOT_NULL, (lambda lhs, rhs: lhs.day == rhs))


class Month(LookupQueryEvaluator):
    evaluators = (NOT_NULL, (lambda lhs, rhs: lhs.month == rhs))


class Year(LookupQueryEvaluator):
    evaluators = (NOT_NULL, (lambda lhs, rhs: lhs.year == rhs))


class WeekDay(LookupQueryEvaluator):
    # Counterintuitively, the __week_day lookup does not use the .weekday()
    # python method, but instead some custom django weekday thing
    # (Sunday=1 to Saturday=7). This is equivalent to:
    # (isoweekday mod 7) + 1.
    # https://docs.python.org/2/library/datetime.html#datetime.date.isoweekday
    #
    # See docs at https://docs.djangoproject.com/en/dev/ref/models/querysets/#week-day
    # and https://code.djangoproject.com/ticket/10345 for additional
    # discussion.
    evaluators = (NOT_NULL, (lambda lhs, rhs: (lhs.isoweekday() % 7) + 1 == rhs))


class Range(LookupQueryEvaluator):
    evaluators = (NOT_NULL, (lambda lhs, rhs: rhs[0] < lhs < rhs[1]))


LOOKUP_TO_EVALUATOR = {
    'contains': Contains,
    'day': Day,
    'endswith': EndsWith,
    'exact': Exact,
    'gt': GT,
    'gte': GTE,
    'icontains': IContains,
    'iendswith': IEndsWith,
    'iexact': IExact,
    'in': In,
    'iregex': IRegex,
    'isnull': IsNull,
    'istartswith': IStartsWith,
    'lt': LT,
    'lte': LTE,
    'month': Month,
    'range': Range,
    'regex': Regex,
    'search': Contains,
    'startswith': StartsWith,
    'week_day': WeekDay,
    'year': Year
}


def get_field_and_accessor(instance_or_model, lookup_part):
    if lookup_part == 'pk':
        field = instance_or_model._meta.pk
        direct = True
    elif django.VERSION < (1, 8):
        field, model, direct, m2m = instance_or_model._meta.get_field_by_name(lookup_part)
    else:
        field = instance_or_model._meta.get_field(lookup_part)
        direct = not field.auto_created or field.concrete
    return field, (lookup_part if direct else field.get_accessor_name())
