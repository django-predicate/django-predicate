import copy
import itertools

from django.utils.tree import Node

from django.core.exceptions import FieldDoesNotExist
from django.core.exceptions import MultipleObjectsReturned
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db.models import Manager
from django.db.models import QuerySet
from django.db.models.constants import LOOKUP_SEP
from django.db.models.query import REPR_OUTPUT_SIZE
from django.db.models.query_utils import Q
from django.utils.functional import cached_property

from .lookup_utils import get_field_and_accessor
from .lookup_utils import LOOKUP_TO_EVALUATOR


def eval_wrapper(children, connector):
    """
    generator to yield child nodes, or to wrap filter expressions
    """
    lookups = LookupNode(connector=connector)
    for child in children:
        if isinstance(child, P):
            yield child
        elif isinstance(child, Q):
            yield P._new_instance(child.children, child.connector, child.negated)
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
        evaluators = {self.AND: all, self.OR: any}
        evaluator = evaluators[self.connector]
        ret = evaluator(
            c.eval(instance) for c in eval_wrapper(self.children, connector=self.connector))
        if self.negated:
            return not ret
        else:
            return ret

    def add(self, data, conn_type, squash=True):
        """
        Adapted from `django.utils.tree.Node.add`` to handle the case of
        repeating the same lookup.  This isn't well handled by LookupTree, so we
        need to specially handle cases like ``P(x=1) | P(x=2)``.
        """
        if data in self.children:
            return data
        if not squash:
            self.children.append(data)
            return data
        if self.connector == conn_type:
            if (isinstance(data, Node) and not data.negated
                    and (data.connector == conn_type or len(data) == 1)):
                for child in data.children:
                    self.add(child, conn_type, squash=squash)
                return self
            else:
                if isinstance(data, tuple) and any(
                        isinstance(child, tuple) and child[0] == data[0]
                        for child in self.children):
                    # Special handling for cases where we already have this lookup.
                    self.add(type(self)(data), conn_type, squash=False)
                else:
                    self.children.append(data)
                return data
        else:
            obj = self._new_instance(self.children, self.connector,
                                     self.negated)
            self.connector = conn_type
            self.children = [obj, data]
            return data

    def __invert__(self):
        if len(self.children) == 1:
            return super(P, self).__invert__()

        # Special handling for negation of OR conditions. This helps work around
        # De Morgan law violations in django < 1.10 (and possibly also 1.10).
        obj = type(self)()
        if self.connector == self.OR:
            obj.connector = self.AND
        elif self.connector == self.AND:
            obj.connector = self.OR
        else:
            raise NotImplementedError('Unhandled connector %s' % self.connector)
        for child in self.children:
            if isinstance(child, tuple):
                # (lookup, value) pair.
                new_child = ~type(self)(child)
            else:
                new_child = ~child
            obj.children.append(new_child)
        return obj

    def filter(self, iterable):
        """
        Returns a filtered list of applying self to the elements of iterable.

        This is a similar API to QuerySet.filter.
        """
        return list(filter(self.eval, iterable))

    def exclude(self, iterable):
        """
        Returns a filtered list of applying ~self to the elements of iterable.

        This is a similar API to QuerySet.exclude.
        """
        return list(filter((~self).eval, iterable))

    def get(self, iterable):
        """
        Gets the unique element of iterable that matches self.

        This follows the QuerySet.get() api, raising ObjectDoesNotExist if no
        element matches and MultipleObjectsReturned if multiple objects match.
        """
        filtered = self.filter(iterable)
        if len(filtered) == 0:
            raise ObjectDoesNotExist('Object matching query does not exist.')
        elif len(filtered) > 1:
            raise MultipleObjectsReturned(
                'get() returned more than one object -- it returned %s!' % len(filtered))
        else:
            return filtered[0]


class LookupNotFound(Exception):
    pass


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
        return [cls(component) for component in lookup.split(LOOKUP_SEP)]

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

    def _get_django_field_lookup(self, obj):
        """
        Attempts to get the lookup specified by self using django's field accessor.

        Raises FieldDoesNotExist if the field cannot be found.
        """
        field, accessor = get_field_and_accessor(obj, self)
        try:
            return getattr(obj, accessor)
        except ObjectDoesNotExist:
            # Occurs in evaluating reverse OneToOneField relationships.
            return None

    def _apply_lookup(self, obj):
        """
        Returns the result of applying this lookup, via either:
         - The django field accessor if defined.
         - `getattr` if the object has the appropriate attribute.
         - `__getitem__` if the object has a matching key (in a dict).
        """
        if isinstance(obj, models.Model):
            try:
                return self._get_django_field_lookup(obj)
            except (FieldDoesNotExist, AttributeError):
                pass
        if hasattr(obj, self):
            return getattr(obj, self)
        elif isinstance(obj, dict):
            try:
                return obj[self]
            except KeyError:
                pass
        raise LookupNotFound(self, obj)

    def values_list(self, obj):
        if obj is None:
            return [None]
        elif self == LookupComponent.EMPTY:
            return [obj]
        result = self._apply_lookup(obj)
        if isinstance(result, (QuerySet, Manager)):
            return result.all()
        elif isinstance(result, (list, tuple)):
            return result
        else:
            return [result]


LookupComponent.EMPTY = LookupComponent('')
UNDEFINED = object()
GET = object()


class LookupNode(object):
    def __init__(self, lookups=None, connector=Q.AND):
        lookups = lookups or {}
        self.connector = connector
        self.children = {}
        if lookups:
            for lookup, value in lookups.items():
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

    def items(self, lookup_stack=None):
        # This function is named `items` so that either a Node or a dict can have the same calls.
        lookup_stack = [] if lookup_stack is None else lookup_stack
        for component, node in self.children.items():
            if component == LookupComponent.EMPTY:
                yield (LookupComponent(LOOKUP_SEP.join(lookup_stack)),
                       self.value)
            else:
                lookup_stack.append(component)
                for item in node.items(lookup_stack=lookup_stack):
                    yield item
                lookup_stack.pop()

    def to_dict(self):
        return dict(self.items())

    def __repr__(self):
        return 'LookupNode(lookups=%r)' % self.to_dict()

    @cached_property
    def evaluators(self):
        return [query.build_evaluator(rhs) for query, rhs in self.items()]

    def eval(self, instance):
        query_values_lookups = self.convert_to_query_values_node()
        values = query_values_lookups.values(instance)
        for node in values:
            if self.connector == Q.AND:
                node_matches = True
            elif self.connector == Q.OR:
                node_matches = False
            else:
                raise NotImplementedError(self.connector)
            for lookup, value in node.items():
                queries = self[lookup]
                if self.connector == Q.AND:
                    node_matches &= all(
                        evaluator(value) for evaluator in queries.evaluators)
                elif self.connector == Q.OR:
                    node_matches |= any(
                        evaluator(value) for evaluator in queries.evaluators)
                else:
                    raise NotImplementedError(self.connector)

            if node_matches:
                return True
        return False

    def convert_to_query_values_node(self):
        """
        Returns a version of self that has had all query lookup components
        replaced by GET operations.

        Used for evaluating predicates.
        """
        lookups = LookupNode(connector=self.connector)
        for lookup, _ in self.items():
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
            zip(itertools.repeat(lookup), values)
            for lookup, values in lookup2values.items())
        results = []
        for child_product in itertools.product(*children_iters):
            node = LookupNode()
            for lookup, value in child_product:
                node.children[lookup] = value
            results.append(node)
        return results


def get_values_list(obj, *lookups, **kwargs):
    """
    Convenience method that simulates the effect of QuerySet.values_list.

    Other than ordering, this should behave identically to the following for
    Django model instances and lookups on django fields:
        SomeModel.objects.filter(pk=obj.pk).values_list(*lookups, **kwargs)
    """
    flat = kwargs.pop('flat', False)
    if kwargs:
        raise TypeError('Unexpected keyword arguments to values_list: %s' %
                        kwargs.keys())
    if flat and len(lookups) > 1:
        raise TypeError("'flat' is not valid when values_list is called with more than one field.")  # noqa:E501

    lookup_node = LookupNode(lookups={lookup: GET for lookup in lookups})
    value_dicts = lookup_node.values(obj)
    if flat:
        [lookup] = lookups
        return [value_dict[lookup].value for value_dict in value_dicts]
    else:
        return [tuple(value_dict[lookup].value for lookup in lookups)
                for value_dict in value_dicts]


class PredicateQuerySet(object):
    """
    Iterable wrapper that follows the QuerySet API.
    """
    def __init__(self, iterable, p=None):
        self._evaluated = False
        self.iterable = iterable
        if p is None:
            p = P()
        self.P = p

    def _evaluate(self):
        """
        Applies own filters to stored iterable.
        """
        if self._evaluated:
            return
        self._evaluated = True
        self.iterable = self.P.filter(self.iterable)

    def __repr__(self):
        self._evaluate()
        data = self.iterable[:REPR_OUTPUT_SIZE + 1]
        if len(data) > REPR_OUTPUT_SIZE:
            data[-1] = "...(remaining elements truncated)..."
        return '<PredicateQuerySet %r>' % data

    def __getitem__(self, k):
        self._evaluate()
        if isinstance(k, slice):
            return self.__class__(self.iterable[k])
        return self.iterable[k]

    def __iter__(self):
        return iter(self.iterable)

    def _clone(self):
        clone = type(self)(None)
        for name, value in self.__dict__.items():
            setattr(clone, name, copy.deepcopy(value))
        clone._evaluated = False
        return clone

    def all(self):
        return self._clone()

    def filter(self, *args, **kwargs):
        clone = self._clone()
        clone.P = clone.P & P(*args, **kwargs)
        return clone

    def exclude(self, *args, **kwargs):
        clone = self._clone()
        clone.P = clone.P & ~P(*args, **kwargs)
        return clone

    def get(self, *args, **kwargs):
        clone = self.filter(*args, **kwargs)
        return clone.P.get(clone.iterable)

    def exists(self):
        self._evaluate()
        return bool(self.iterable)

    def count(self):
        self._evaluate()
        return len(self.iterable)

    def _combine(self, other, connector):
        clone1 = self._clone()
        clone2 = other._clone()

        if connector == Q.AND:
            iterable = filter(set(clone1).__contains__, clone2)
            p = clone1.P & clone2.P
        elif connector == Q.OR:
            iterable = list(itertools.chain(clone1, clone2))
            p = clone2.P | clone2.P
        else:
            raise ValueError('Invalid logical connector: %s' % connector)

        return type(self)(iterable, p=p)

    def __and__(self, other):
        return self._combine(other, Q.AND)

    def __or__(self, other):
        return self._combine(other, Q.OR)

    def __bool__(self):
        self._evaluate()
        return bool(self.iterable)

    def __nonzero__(self):
        return type(self).__bool__(self)
