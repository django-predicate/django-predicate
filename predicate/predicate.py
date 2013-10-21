import re

from django.db.models.manager import Manager
from django.db.models.query_utils import Q
from django.utils.datastructures import SortedDict

LOOKUP_SEP = '__'

QUERY_TERMS = set([
    'exact', 'iexact', 'contains', 'icontains', 'gt', 'gte', 'lt', 'lte', 'in',
    'startswith', 'istartswith', 'endswith', 'iendswith', 'range', 'year',
    'month', 'day', 'week_day', 'isnull', 'search', 'regex', 'iregex', 'any',
])


class LookupExpression(object):
    """
    A thin wrapper around a filter expression tuple of (lookup-type, value) to
    provide an eval method
    """

    def __init__(self, expr):
        self.lookup, self.value = expr
        self.field = None

    def get_field(self, instance):
        """
        Returns the value of this lookup on the given instance.

        If the path ends with a value having the same name as a lookup
        type (like "year", "range", etc.), the lookup must provide an
        explicit type, such as "__exact".

        Lookups can span Django fields, dicts, lists, or other integer-
        indexed iterables.
        """

        def traverse_attr(o, attr, reraise=False):
            # Convert numbers to integers to allow list indexing
            if attr.isdigit():
                attr = int(attr)

            # M2M relations are a special case
            if isinstance(o, Manager):
                if isinstance(attr, int):
                    return o.all()[attr]
                else:
                    return list(o.values_list(attr, flat=True))

            try:
                # If this object supports indexing, return the
                # value indexed by `attr`
                return o[attr]
            except (IndexError, KeyError):
                # If this object supports indexing but the index
                # does not contain `attr`, return `None`.
                return None
            except TypeError:
                # Nesting these `TypeError`s sucks, but Python doesn't
                # raise an `AttributeError` on missing `__getitem__`
                # like it should, making it impossible to handle that
                # case in a separate block.
                try:
                    # If this object is iterable, try to make a list
                    # by traversing the attr across each of its items.
                    return [traverse_attr(item, attr) for item in o]
                except TypeError:
                    # If this object does not support indexing, call
                    # `getattr` to get the value.
                    return getattr(o, attr, None)

        # Strip off known lookup types from the end of the lookup
        lookup_type = 'exact'
        parts = self.lookup.split(LOOKUP_SEP)
        if parts[-1] in QUERY_TERMS:
            lookup_type = parts[-1]
            parts = parts[:-1]

        # Traverse the lookup to the value, starting with the instance
        value = reduce(traverse_attr, parts, instance)

        return (instance, value, lookup_type)

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
        return lookup_field == self.value

    def _iexact(self, lookup_model, lookup_field):
        return lookup_field.lower() == self.value.lower()

    def _contains(self, lookup_model, lookup_field):
        return self.value in lookup_field

    def _icontains(self, lookup_model, lookup_field):
        return self.value.lower() in lookup_field.lower()

    def _gt(self, lookup_model, lookup_field):
        return lookup_field > self.value

    def _gte(self, lookup_model, lookup_field):
        return lookup_field >= self.value

    def _lt(self, lookup_model, lookup_field):
        return lookup_field < self.value

    def _lte(self, lookup_model, lookup_field):
        return lookup_field <= self.value

    def _startswith(self, lookup_model, lookup_field):
        return lookup_field.startswith(self.value)

    def _istartswith(self, lookup_model, lookup_field):
        return lookup_field.lower().startswith(self.value.lower())

    def _endswith(self, lookup_model, lookup_field):
        return lookup_field.endswith(self.value)

    def _iendswith(self, lookup_model, lookup_field):
        return lookup_field.lower().endswith(self.value.lower())

    def _range(self, lookup_model, lookup_field):
        # TODO could be more between like
        return self.value[0] < lookup_field < self.value[1]

    def _year(self, lookup_model, lookup_field):
        return lookup_field.year == self.value

    def _month(self, lookup_model, lookup_field):
        return lookup_field.month == self.value

    def _day(self, lookup_model, lookup_field):
        return lookup_field.day == self.value

    def _week_day(self, lookup_model, lookup_field):
        return lookup_field.weekday() == self.value

    def _isnull(self, lookup_model, lookup_field):
        if self.value:
            return lookup_field == None
        else:
            return lookup_field != None

    def _search(self, lookup_model, lookup_field):
        return self._contains(lookup_model, lookup_field)

    def _regex(self, lookup_model, lookup_field):
        """
        Note that for queries - this can be DB specific syntax
        here we just use Python
        """
        return bool(re.search(self.value, lookup_field))

    def _iregex(self, lookup_model, lookup_field):
        return bool(re.search(self.value, lookup_field, flags=re.I))

    def _in(self, instance, lookup_value):
        """
        Evaluates whether the lookup list and this value list intersect.
        """
        return bool(set(lookup_value) & set(self.value))

    def _any(self, instance, lookup_value):
        """
        Evaluates whether the lookup list contains this value.
        """
        return self.value in lookup_value


class P(Q):
    """
    A Django 'predicate' construct

    This is a variation on Q objects, but instead of being used to generate
    SQL, they are used to test a model instance against a set of conditions.

    P-objects can also evaluate dicts with equivalence to Django models.

    For example::

        >>> {'username': 'testuser'} in P(username='testuser')
        True
        >>> User(username='testuser') in P(username='testuser')
        True
    """

    ##############
    # Evaluation #
    ##############

    wrapper = LookupExpression

    def eval(self, instance):
        evaluators = {"AND": all, "OR": any}
        evaluator = evaluators[self.connector]
        return (evaluator(self.wrap(c).eval(instance) for c in self.children))

    def wrap(self, node):
        return node if isinstance(node, P) else self.wrapper(node)

    #################
    # Serialization #
    #################

    def to_dict(self):
        return SortedDict({
            'negated': self.negated,
            'connector': self.connector,
            'children': [
                c.to_dict() if isinstance(c, P) else c
                for c in sorted(self.children)
            ],
        })

    @classmethod
    def from_dict(cls, d):
        p = P()
        p.connector = d.get('connector', cls.default)
        p.negated = d.get('negated', False)
        p.children = [
            cls.from_dict(c) if isinstance(c, dict) else c
            for c in d.get('children', [])
        ]
        return p

    ##############
    # Comparison #
    ##############

    # allow the use of the 'in' operator for membership testing
    def __contains__(self, obj):
        return self.eval(obj)

    def __eq__(self, other):
        if not hasattr(other, 'to_dict'):
            return False
        else:
            return self.to_dict() == other.to_dict()
