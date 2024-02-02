from copy import deepcopy
from contextlib import contextmanager

from predicate import P
from predicate import PredicateQuerySet

original_eval = P.eval


def orm_eval(predicate, instance):
    """
    Implementation of P semantics that asserts the ORM and P have the same
    semantics. Also validates negation logic on the provided query

    This is much slower than P.eval, but can be used for debugging
    discrepancies with the ORM, or validating there are none.
    """
    manager = type(instance)._default_manager

    orm_value = manager.filter(predicate, pk=instance.pk).exists()
    super_value = original_eval(predicate, instance)
    assert orm_value == super_value

    return super_value


class OrmP(P):
    """
    Version of P class that asserts the invariants of the orm_eval method.
    """
    def eval(self, instance):
        return orm_eval(self, instance)


@contextmanager
def patch_with_orm_eval():
    """
    Patches P.eval with the orm_eval version for debugging and validation.

    Requires the `mock` package.  Usage:
        from predicate.debug import patch_with_orm_eval
        with patch_with_orm_eval():
            some_code_where_calling_P()

    This will evaluate both in-memory, and via a roundtrip to the database, so
    should not be used in production code.
    """
    try:
        P.eval = orm_eval
        yield
    finally:
        P.eval = original_eval


original_filter = PredicateQuerySet.filter


def orm_filter(predicate, instance):
    manager = type(instance)._default_manager
    orm_value = manager.filter(predicate, pk=instance.pk).exists()
    super_value = original_filter(predicate, instance)
    assert orm_value == super_value
    return super_value


class OrmPredicateQuerySet(object):
    """
    Wraps a QuerySet and a PredicateQuerySet. Calls the same methods on both,
    and asserts they return the same value.
    """
    def __init__(self, queryset, predicatequeryset=None):
        """
        Args:
            queryset (django.db.models.QuerySet)
        """
        self.qs = queryset
        self.pqs = predicatequeryset or PredicateQuerySet(queryset)

    def _call_on_iterables(self, method, *args, **kwargs):
        pqs_value = getattr(self.pqs, method)(*args, **kwargs)
        qs_value = getattr(self.qs, method)(*args, **kwargs)

        if isinstance(pqs_value, PredicateQuerySet):
            self._assert_iterables_equal()
            return type(self)(qs_value, predicatequeryset=pqs_value)
        else:
            assert pqs_value == qs_value
            return pqs_value

    def _assert_iterables_equal(self):
        pqs = deepcopy(self.pqs)
        qs = deepcopy(self.qs)
        assert list(pqs) == list(qs)

    def all(self, *args, **kwargs):
        return self._call_on_iterables('all', *args, **kwargs)

    def get(self, *args, **kwargs):
        return self._call_on_iterables('get', *args, **kwargs)

    def filter(self, *args, **kwargs):
        return self._call_on_iterables('filter', *args, **kwargs)

    def exclude(self, *args, **kwargs):
        return self._call_on_iterables('exclude', *args, **kwargs)

    def exists(self, *args, **kwargs):
        return self._call_on_iterables('exists', *args, **kwargs)

    def count(self, *args, **kwargs):
        return self._call_on_iterables('count', *args, **kwargs)

    def __and__(self, *args, **kwargs):
        return self._call_on_iterables('__and__', *args, **kwargs)

    def __or__(self, *args, **kwargs):
        return self._call_on_iterables('__or__', *args, **kwargs)
