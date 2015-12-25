import re

import django
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Manager
from django.db.models import QuerySet
from django.db.models.query_utils import Q

LOOKUP_SEP = '__'

QUERY_TERMS = set([
    'exact', 'iexact', 'contains', 'icontains', 'gt', 'gte', 'lt', 'lte', 'in',
    'startswith', 'istartswith', 'endswith', 'iendswith', 'range', 'year',
    'month', 'day', 'week_day', 'isnull', 'search', 'regex', 'iregex',
])


def eval_wrapper(children):
    """
    generator to yield child nodes, or to wrap filter expressions
    """
    for child in children:
        if isinstance(child, P):
            yield child
        elif isinstance(child, tuple) and len(child) == 2:
            yield LookupEvaluator(child)
        else:
            raise ValueError(child)


class P(Q):
    """
    A Django 'predicate' construct

    This is a variation on Q objects, but instead of being used to generate
    SQL, they are used to test a model instance against a set of conditions.
    """

    # allow the use of the 'in' operator for membership testing
    def __contains__(self, obj):
        # TODO: This overrides Q's __contains__ method. It should only have
        # the custom behavior for non-Node objects.
        return self.eval(obj)

    def eval(self, instance):
        """
        Returns true if the model instance matches this predicate
        """
        evaluators = {"AND": all, "OR": any}
        evaluator = evaluators[self.connector]
        ret = evaluator(c.eval(instance) for c in eval_wrapper(self.children))
        if self.negated:
            return not ret
        else:
            return ret


class LookupEvaluator(object):
    """
    A thin wrapper around a filter expression tuple of (lookup-type, value) to
    provide an eval method
    """

    def __init__(self, expr):
        self.lookup, self.value = expr

    def get_field_from_objs(self, lookup_name, objs):
        values = []
        for obj in objs:
            if obj is None:
                values.append(None)
                continue
            if django.VERSION < (1, 8):
                field, model, direct,  m2m = obj._meta.get_field_by_name(
                    lookup_name)
            else:
                field = obj._meta.get_field(lookup_name)
                direct = not field.auto_created or field.concrete
            accessor = lookup_name if direct else field.get_accessor_name()
            try:
                result = getattr(obj, accessor)
            except ObjectDoesNotExist:
                values.append(None)
            else:
                if isinstance(result, (QuerySet, Manager)):
                    values.extend(result.all())
                else:
                    values.append(result)
        return values

    def get_field(self, instance):
        parts = self.lookup.split(LOOKUP_SEP)

        lookup_type = 'exact'  # Default lookup type
        if parts[-1] in QUERY_TERMS:
            lookup_type = parts.pop()
        values = [instance]
        for part in parts:
            values = self.get_field_from_objs(part, values)
        return instance, values, lookup_type

    def eval(self, instance):
        """
        return true if the instance matches the expression
        """
        lookup_model, lookup_field, lookup_type = self.get_field(instance)
        comparison_func = getattr(self, '_' + lookup_type, None)
        if comparison_func:
            return comparison_func(lookup_field)
        raise ValueError("invalid lookup: {}".format(self.lookup))

    # Comparison functions

    def _exact(self, values):
        return self.value in values

    def _iexact(self, values):
        expected = self.value.lower()
        return any(value is not None and expected == value.lower()
                   for value in values)

    def _contains(self, values):
        return any(value is not None and self.value in value
                   for value in values)

    def _icontains(self, values):
        expected = self.value.lower()
        return any(value is not None and expected in value
                   for value in values)

    def _gt(self, values):
        return any(value is not None and value > self.value
                   for value in values)

    def _gte(self, values):
        return any(value is not None and value >= self.value
                   for value in values)

    def _lt(self, values):
        return any(value is not None and value < self.value
                   for value in values)

    def _lte(self, values):
        return any(value is not None and value <= self.value
                   for value in values)

    def _startswith(self, values):
        return any(value is not None and value.startswith(self.value)
                   for value in values)

    def _istartswith(self, values):
        expected_value = self.value.lower()
        return any(
            value is not None and value.lower().startswith(expected_value)
            for value in values)

    def _endswith(self, values):
        return any(
            value is not None and value.lower().endswith(self.value)
            for value in values)

    def _iendswith(self, values):
        expected_value = self.value.lower()
        return any(
            value is not None and value.lower().endswith(expected_value)
            for value in values)

    def _in(self, values):
        return bool(set(values) & set(self.value))

    def _range(self, values):
        return any(value is not None and self.value[0] < value < self.value[1]
                   for value in values)

    def _year(self, values):
        return any(value is not None and value.year == self.value
                   for value in values)

    def _month(self, values):
        return any(value is not None and value.month == self.value
                   for value in values)

    def _day(self, values):
        return any(value is not None and value.day == self.value
                   for value in values)

    def _week_day(self, values):
        # Counterintuitively, the __week_day lookup does not use the .weekday()
        # python method, but instead some custom django weekday thing
        # (Sunday=1 to Saturday=7). This is equivalent to:
        # (isoweekday mod 7) + 1.
        # https://docs.python.org/2/library/datetime.html#datetime.date.isoweekday
        #
        # See docs at https://docs.djangoproject.com/en/dev/ref/models/querysets/#week-day
        # and https://code.djangoproject.com/ticket/10345 for additional
        # discussion.
        return any(
            value is not None
            and (value.isoweekday() % 7) + 1 == self.value
            for value in values)

    def _isnull(self, values):
        if self.value:
            return None in values
        else:
            return None not in values

    def _search(self, values):
        return self._contains(values)

    def _regex(self, values):
        """
        Note that for queries - this can be DB specific syntax
        here we just use Python
        """
        regex = re.compile(self.value)
        return any(
            value is not None and regex.search(value)
            for value in values)

    def _iregex(self, values):
        regex = re.compile(self.value, flags=re.I)
        return any(
            value is not None and regex.search(value)
            for value in values)
