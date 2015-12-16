import re

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
        return s.replace('_','')

class LookupExpression(object):
    """
    A thin wrapper around a filter expression tuple of (lookup-type, value) to
    provide an eval method
    """

    def __init__(self, expr):
        self.lookup, self.value = expr
        self.field = None

    def get_field(self, instance):
        lookup_type = 'exact' # Default lookup type
        parts = self.lookup.split(LOOKUP_SEP)
        num_parts = len(parts)
        if (len(parts) > 1 and parts[-1] in QUERY_TERMS):
            # Traverse the lookup query to distinguish related fields from
            # lookup types.
            lookup_model = instance
            for counter, field_name in enumerate(parts):
                try:
                    lookup_field = getattr(lookup_model, field_name)
                except AttributeError:
                    # Not a field. Bail out.
                    lookup_type = parts.pop()
                    return (lookup_model, lookup_field, lookup_type)
                # Unless we're at the end of the list of lookups, let's attempt
                # to continue traversing relations.
                if (counter + 1) < num_parts:
                    try:
                        dummy = lookup_model._meta.get_field(field_name).rel.to
                        lookup_model = lookup_field
                        # print lookup_model
                    except AttributeError:
                        # # Not a related field. Bail out.
                        lookup_type = parts.pop()
                        return (lookup_model, lookup_field, lookup_type)
        else:
            return (instance, getattr(instance, parts[0]), lookup_type)

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

    def _in(self, lookup_model, lookup_field):
        return lookup_field in self.value

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


