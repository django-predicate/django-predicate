import re

import django
from django.core.exceptions import ObjectDoesNotExist
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
            yield LookupExpression(child)


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

    def to_identifier(self):
        s = ""
        for c in sorted(self.children):
            if isinstance(c, type(self)):
                s += c.to_identifier()
            else:
                s += ''.join([str(val) for val in c])
        return s.replace('_', '')


class LookupExpression(object):
    """
    A thin wrapper around a filter expression tuple of (lookup-type, value) to
    provide an eval method
    """

    def __init__(self, expr):
        self.lookup, self.value = expr
        self.field = None

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
                if hasattr(result, 'all'):
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
            return comparison_func(lookup_model, lookup_field)
        raise ValueError("invalid lookup: {}".format(self.lookup))

    # Comparison functions

    def _exact(self, lookup_model, lookup_field):
        return self.value in lookup_field

    def _iexact(self, lookup_model, lookup_field):
        expected = self.value.lower()
        return any(value is not None and expected == value.lower()
                   for value in lookup_field)

    def _contains(self, lookup_model, lookup_field):
        return any(value is not None and self.value in value
                   for value in lookup_field)

    def _icontains(self, lookup_model, lookup_field):
        expected = self.value.lower()
        return any(value is not None and expected in value
                   for value in lookup_field)

    def _gt(self, lookup_model, lookup_field):
        return any(value is not None and value > self.value
                   for value in lookup_field)

    def _gte(self, lookup_model, lookup_field):
        return any(value is not None and value >= self.value
                   for value in lookup_field)

    def _lt(self, lookup_model, lookup_field):
        return any(value is not None and value < self.value
                   for value in lookup_field)

    def _lte(self, lookup_model, lookup_field):
        return any(value is not None and value <= self.value
                   for value in lookup_field)

    def _startswith(self, lookup_model, lookup_field):
        return any(value is not None and value.startswith(self.value)
                   for value in lookup_field)

    def _istartswith(self, lookup_model, lookup_field):
        expected_value = self.value.lower()
        return any(
            value is not None and value.lower().startswith(expected_value)
            for value in lookup_field)

    def _endswith(self, lookup_model, lookup_field):
        return any(
            value is not None and value.lower().endswith(self.value)
            for value in lookup_field)

    def _iendswith(self, lookup_model, lookup_field):
        expected_value = self.value.lower()
        return any(
            value is not None and value.lower().endswith(expected_value)
            for value in lookup_field)

    def _in(self, lookup_model, lookup_field):
        return bool(set(lookup_field) & set(self.value))

    def _range(self, lookup_model, lookup_field):
        return any(value is not None and self.value[0] < value < self.value[1]
                   for value in lookup_field)

    def _year(self, lookup_model, lookup_field):
        return any(value is not None and value.year == self.value
                   for value in lookup_field)

    def _month(self, lookup_model, lookup_field):
        return any(value is not None and value.month == self.value
                   for value in lookup_field)

    def _day(self, lookup_model, lookup_field):
        return any(value is not None and value.day == self.value
                   for value in lookup_field)

    def _week_day(self, lookup_model, lookup_field):
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
            for value in lookup_field)

    def _isnull(self, lookup_model, lookup_field):
        if self.value:
            return None in lookup_field
        else:
            return None not in lookup_field

    def _search(self, lookup_model, lookup_field):
        return self._contains(lookup_model, lookup_field)

    def _regex(self, lookup_model, lookup_field):
        """
        Note that for queries - this can be DB specific syntax
        here we just use Python
        """
        regex = re.compile(self.value)
        return any(
            value is not None and regex.search(value)
            for value in lookup_field)

    def _iregex(self, lookup_model, lookup_field):
        regex = re.compile(self.value, flags=re.I)
        return any(
            value is not None and regex.search(value)
            for value in lookup_field)
