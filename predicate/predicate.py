import itertools

import django
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Manager
from django.db.models import QuerySet
from django.db.models.constants import LOOKUP_SEP
from django.db.models.query_utils import Q
from django.utils.functional import cached_property

from .lookup_utils import LOOKUP_TO_EVALUATOR


def eval_wrapper(children):
    """
    generator to yield child nodes, or to wrap filter expressions
    """
    lookups = LookupNode()
    for child in children:
        if isinstance(child, P):
            yield child
        elif isinstance(child, tuple):
            lookup, value = child
            lookups[lookup] = value
        else:
            raise ValueError(child)
    yield lookups


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


class LookupComponent(str):
    def __repr__(self):
        return '{self.__class__.__name__}({repr})'.format(
            self=self,
            repr=super(LookupComponent, self).__repr__())

    @classmethod
    def parse(cls, lookup):
        """
        Parses a lookup__string into a list of LookupComponent objects.
        """
        if not lookup:  # Handle '' standing in for leaf components in lookups.
            return []
        return map(cls, lookup.split(LOOKUP_SEP))

    @property
    def is_query(self):
        """
        Returns true if a query lookup like __in or __gte.

        TODO: Expand this to handle custom registered lookups.
        """
        return self in LOOKUP_TO_EVALUATOR

    def build_evaluator(self, rhs):
        # No query lookup was specified, so assume __exact
        query = 'exact' if self == LookupComponent.EMPTY else self
        return LOOKUP_TO_EVALUATOR[query](rhs)

    def values_list(self, obj):
        if obj is None:
            return [None]
        elif self == LookupComponent.EMPTY:
            return [obj]
        values = []
        if self == 'pk':
            field = obj._meta.pk
            direct = True
        elif django.VERSION < (1, 8):
            field, model, direct,  m2m = obj._meta.get_field_by_name(self)
        else:
            field = obj._meta.get_field(self)
            direct = not field.auto_created or field.concrete
        accessor = self if direct else field.get_accessor_name()
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


LookupComponent.EMPTY = LookupComponent('')
UNDEFINED = object()
GET = object()


class LookupNode(object):
    def __init__(self, lookups=None):
        lookups = lookups or {}
        self.children = {}
        if lookups is not None:
            for lookup, value in lookups.viewitems():
                self[lookup] = value

    @property
    def value(self):
        return self.children.get(LookupComponent.EMPTY, UNDEFINED)

    @value.setter
    def value(self, value):
        self.children[LookupComponent.EMPTY] = value

    def __setitem__(self, lookup, value):
        components = LookupComponent.parse(lookup)
        cur = self
        for component in components:
            prev = cur
            cur = cur.children.get(component)
            if cur is None:
                prev.children[component] = cur = LookupNode()
        cur.value = value

    def __getitem__(self, lookup):
        components = LookupComponent.parse(lookup)
        cur = self
        for component in components:
            cur = cur.children[component]
        return cur

    def iteritems(self, lookup_stack=None):
        lookup_stack = [] if lookup_stack is None else lookup_stack
        for component, node in self.children.viewitems():
            if component == LookupComponent.EMPTY:
                yield (LookupComponent(LOOKUP_SEP.join(lookup_stack)),
                       self.value)
            else:
                lookup_stack.append(component)
                for item in node.iteritems(lookup_stack=lookup_stack):
                    yield item
                lookup_stack.pop()

    def to_dict(self):
        return dict(self.iteritems())

    def __repr__(self):
        return 'LookupNode(lookups=%r)' % self.to_dict()

    @cached_property
    def evaluators(self):
        return [query.build_evaluator(rhs) for query, rhs in self.iteritems()]

    def eval(self, instance):
        query_values_lookups = self.convert_to_query_values_node()
        values = query_values_lookups.values(instance)
        for node in values:
            node_matches = True
            for lookup, value in node.iteritems():
                queries = self[lookup]
                node_matches &= all(
                    evaluator(value) for evaluator in queries.evaluators)
            if node_matches:
                return True
        return False

    def convert_to_query_values_node(self):
        """
        Returns a version of self that has had all query lookup components
        replaced by GET operations.

        Used for evaluating predicates.
        """
        lookups = LookupNode()
        for lookup, _ in self.iteritems():
            parsed = LookupComponent.parse(lookup)
            if parsed[-1].is_query:
                parsed.pop()
            lookups[LOOKUP_SEP.join(parsed)] = GET
        return lookups

    def values(self, obj):
        """
        Returns a list of LookupNode instances matching the GET lookups in self.
        """
        lookup2values = {}
        for lookup, child in self.children.items():
            lookup_objects = lookup.values_list(obj)
            if lookup == LookupComponent.EMPTY:
                child_values = lookup_objects
            else:
                child_values = []
                for lookup_obj in lookup_objects:
                    child_values.extend(child.values(lookup_obj))
            lookup2values[lookup] = child_values

        # Construct a cartesian product of all returned values. This
        # corresponds to a database join among the lookups.
        # TODO: Does this handle inner and outer joins properly?
        children_iters = (
            itertools.izip(itertools.repeat(lookup), values)
            for lookup, values in lookup2values.items())
        results = []
        for child_product in itertools.product(*children_iters):
            node = LookupNode()
            for lookup, value in child_product:
                node.children[lookup] = value
            results.append(node)
        return results
