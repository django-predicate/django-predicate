from contextlib import contextmanager

from nose.tools import assert_equal

from predicate import P

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
    assert_equal(orm_value, super_value)

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
    from mock import patch
    with patch.object(P, eval=orm_eval):
        yield

