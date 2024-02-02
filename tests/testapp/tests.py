# -*- coding: utf-8 -*-

from datetime import date
from datetime import datetime
from datetime import timedelta
from random import choice, random
from unittest import expectedFailure

import mock
from django.core.exceptions import MultipleObjectsReturned
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.test import skipIfDBFeature
from django.test import TestCase

from predicate.debug import OrmP
from predicate.debug import patch_with_orm_eval
from predicate.debug import OrmPredicateQuerySet
from predicate.predicate import GET
from predicate.predicate import get_values_list
from predicate.predicate import LookupComponent
from predicate.predicate import LookupNode
from predicate.predicate import LookupNotFound
from predicate import P
from predicate import PredicateQuerySet
from .models import CustomRelatedNameOneToOneModel
from .models import ForeignKeyModel
from .models import M2MModel
from .models import OneToOneModel
from .models import TestObj

colors = """red
blue
yellow
green
orange
purple
violet
brown
black
white""".split('\n')


def make_test_objects():
    made = []

    for i in range(100):
        t = TestObj()
        t.char_value = ' '.join([choice(colors), choice(colors), choice(colors)])
        t.int_value = int(100 * random())
        if made:
            t.parent = choice(made)
        t.save()
        made.append(t)


class RelationshipFollowTest(TestCase):

    def test_random_follow_relationship(self):
        make_test_objects()
        p1 = OrmP(parent__int_value__gt=10)
        obj = TestObj.objects.filter(parent__int_value__gt=10)[0]
        self.assertTrue(p1.eval(obj))
        p2 = OrmP(parent__parent__int_value__gt=10)
        obj = TestObj.objects.filter(parent__parent__int_value__gt=10)[0]
        self.assertTrue(p2.eval(obj))

    def test_children_relationship_single(self):
        parent = TestObj.objects.create(int_value=100)
        TestObj.objects.bulk_create([
            TestObj(int_value=i, parent=parent) for i in range(3)
        ])
        self.assertIn(parent, TestObj.objects.filter(OrmP(children__int_value=2)))
        pred = OrmP(children__int_value=2)
        self.assertIn(parent, pred)

    def test_direct_one_to_one_relationships(self):
        test_obj = TestObj.objects.create(int_value=1)
        other_test_obj = TestObj.objects.create(int_value=2)
        one_to_one = OneToOneModel.objects.create(
            test_obj=test_obj, int_value=10)

        self.assertIn(one_to_one, OrmP(test_obj=test_obj))
        self.assertIn(one_to_one, OrmP(test_obj__int_value=1))

        self.assertNotIn(one_to_one, OrmP(test_obj=other_test_obj))
        self.assertNotIn(one_to_one, OrmP(test_obj__int_value=2))

    def test_reverse_one_to_one_relationships(self):
        test_obj = TestObj.objects.create()
        one_to_one = OneToOneModel.objects.create(
            test_obj=test_obj, int_value=10)
        other_one_to_one = OneToOneModel.objects.create()

        self.assertNotIn(test_obj, OrmP(onetoonemodel=other_one_to_one))
        self.assertNotIn(test_obj, OrmP(onetoonemodel__int_value=20))

        self.assertIn(test_obj, OrmP(onetoonemodel=one_to_one))
        self.assertIn(test_obj, OrmP(onetoonemodel__int_value=10))

    def test_reverse_one_to_one_relationships_custom_related_name(self):
        test_obj = TestObj.objects.create()
        custom_one_to_one = CustomRelatedNameOneToOneModel.objects.create(
            test_obj=test_obj, int_value=10)
        other_custom_one_to_one = CustomRelatedNameOneToOneModel.objects.create()

        self.assertNotIn(test_obj,
                         OrmP(custom_one_to_one=other_custom_one_to_one))
        self.assertNotIn(test_obj, OrmP(custom_one_to_one__int_value=20))

        self.assertIn(test_obj, OrmP(custom_one_to_one=custom_one_to_one))
        self.assertIn(test_obj, OrmP(custom_one_to_one__int_value=10))

    def test_foreign_key_default_name(self):
        test_obj = TestObj.objects.create(int_value=20)
        fkey = ForeignKeyModel.objects.create(test_obj=test_obj)
        self.assertIn(fkey, OrmP(test_obj=test_obj))
        self.assertIn(fkey, OrmP(test_obj__int_value=20))
        self.assertNotIn(fkey, OrmP(test_obj__int_value=10))

    def test_reverse_foreign_key_default_name(self):
        test_obj = TestObj.objects.create(int_value=20)
        fkey = ForeignKeyModel.objects.create(test_obj=test_obj, int_value=30)
        other_fkey = ForeignKeyModel.objects.create()
        self.assertIn(fkey, test_obj.foreignkeymodel_set.all())
        self.assertIn(test_obj, OrmP(foreignkeymodel=fkey))
        self.assertIn(test_obj, OrmP(foreignkeymodel__int_value=30))
        self.assertNotIn(test_obj, OrmP(foreignkeymodel=other_fkey))

    def test_m2m(self):
        test_obj = TestObj.objects.create(int_value=20)
        m2m = test_obj.m2ms.create(int_value=10)
        self.assertIn(test_obj, OrmP(m2ms=m2m))
        self.assertIn(test_obj, OrmP(m2ms__int_value=10))

        m2m2 = M2MModel.objects.create(int_value=30)
        self.assertNotIn(test_obj, OrmP(m2ms=m2m2))
        self.assertNotIn(test_obj, OrmP(m2ms__int_value=30))


class TestJointConditions(TestCase):

    def setUp(self):
        self.test_obj = TestObj.objects.create()
        self.test_obj.m2ms.create(int_value=10, char_value='foo')
        self.test_obj.m2ms.create(int_value=20, char_value='bar')

        self.test_obj2 = TestObj.objects.create()
        self.test_obj2.m2ms.create(int_value=10, char_value='bar')
        self.test_obj2.m2ms.create(int_value=20, char_value='foo')

    def _assert_P_matches_Q(self, instance, p, q):
        """
        Asserts that P and Q objects evaluate to the same answer (for instance
        model), _and_ that the querysets generate the same results.

        These assertions are necessary, since the tree structure generated by
        P.__invert__ is different between P and Q. They _should_ generate
        equivalent, but not necessarily identical SQL
        """
        manager = type(instance)._default_manager
        transform_pairs = [
            (p, q),
            (~p, ~q),
            (p & ~p, q & ~q),
            # (p | ~p, q | ~q),
            (~(p & ~p), ~(q & ~q)),
            (~(p | ~p), ~(q | ~q)),
        ]
        for predicate, query in transform_pairs:
            self.assertEqual(
                instance in predicate,
                instance in manager.filter(query)
            )
            self.assertEqual(
                instance in predicate,
                instance in manager.filter(predicate)
            )
            self.assertEqual(
                set(manager.filter(p)),
                set(manager.filter(q)),
            )

    def test_joint_conditions(self):
        """
        Test that joint conditions must be on the same aliased instance.

        In particular P(rel__attr1=val1, rel__attr2=val2) produces only a
        single join, so the two conditions must be jointly satisfied on the
        same database row.
        """
        self._assert_P_matches_Q(
            self.test_obj,
            p=P(m2ms__int_value=10, m2ms__char_value='bar'),
            q=Q(m2ms__int_value=10, m2ms__char_value='bar'),
        )
        self._assert_P_matches_Q(
            self.test_obj,
            p=P(m2ms__int_value=10, m2ms__char_value='foo'),
            q=Q(m2ms__int_value=10, m2ms__char_value='foo'),
        )
        self._assert_P_matches_Q(
            self.test_obj,
            p=P(m2ms__int_value=10) & OrmP(m2ms__char_value='bar'),
            q=Q(m2ms__int_value=10) & Q(m2ms__char_value='bar'),
        )

        self._assert_P_matches_Q(
            self.test_obj,
            p=P(m2ms__int_value=10) & OrmP(m2ms__char_value='foo'),
            q=Q(m2ms__int_value=10) & Q(m2ms__char_value='foo'),
        )

    @expectedFailure
    def test_law_of_excluded_middle(self):
        """
        Django appears to obey the law of excluded middle p|~p is always
        satisfied.

        However, it's _not_ the case that p OR ~p is always satisfied, so the
        implementation in P does not match django's in some edge cases.
        """
        p = P(m2ms__int_value=10, m2ms__char_value='bar')
        q = Q(m2ms__int_value=10, m2ms__char_value='bar')
        self._assert_P_matches_Q(self.test_obj, p=p, q=q)

        self.assertNotIn(self.test_obj, p)
        self.assertNotIn(self.test_obj, ~p)
        # Since evaluation of the disjunction is just logical OR of the
        # disjuncts, since the
        self.assertNotIn(self.test_obj, p | ~p)

        self._assert_P_matches_Q(self.test_obj, p=p, q=q)
        self._assert_P_matches_Q(self.test_obj, p=(p | ~p), q=(q | ~q))

    def test_negation_joint_conditions(self):
        self._assert_P_matches_Q(
            self.test_obj,
            p=~P(m2ms__int_value=10, m2ms__char_value='bar'),
            q=~Q(m2ms__int_value=10, m2ms__char_value='bar'),
        )

        self.assertIn(
            self.test_obj,
            TestObj.objects.filter(~~Q(m2ms__int_value=10, m2ms__char_value='bar'))
        )
        self.assertIn(
            self.test_obj,
            ~~P(m2ms__int_value=10, m2ms__char_value='bar'))
        self._assert_P_matches_Q(
            self.test_obj,
            p=~~P(m2ms__int_value=10, m2ms__char_value='bar'),
            q=~~Q(m2ms__int_value=10, m2ms__char_value='bar'),
        )

        self.assertNotIn(
            self.test_obj,
            TestObj.objects.filter(~~~Q(m2ms__int_value=10, m2ms__char_value='bar'))
        )
        self.assertNotIn(
            self.test_obj,
            ~~~P(m2ms__int_value=10, m2ms__char_value='bar'))
        self._assert_P_matches_Q(
            self.test_obj,
            p=~~~P(m2ms__int_value=10, m2ms__char_value='bar'),
            q=~~~Q(m2ms__int_value=10, m2ms__char_value='bar'),
        )

        self.assertIn(
            self.test_obj,
            ~~P(m2ms__int_value=10, m2ms__char_value='foo'))
        self._assert_P_matches_Q(
            self.test_obj,
            q=~~Q(m2ms__int_value=10, m2ms__char_value='foo'),
            p=~~P(m2ms__int_value=10, m2ms__char_value='foo'),
        )

    def test_de_morgan_law(self):
        """
        Tests De Morgan's law as it relates to the Django ORM.

        Surprisingly, the ORM does _not_ obey De Morgan's law in some cases,
        which this test manifests. See also:
            https://github.com/django/django/pull/6005#issuecomment-184016682
        since Django may start to obey De Morgan's law in Django >= 1.10.
        """
        expr = P(m2ms__int_value=10) & OrmP(m2ms__char_value='bar')
        transformed_expr = ~(~P(m2ms__int_value=10) | ~P(m2ms__char_value='bar'))
        # By De Morgan's law, these expressions are equivalent:
        #     (A ∧ B) ⇔ ¬(¬A ∨ ¬B)
        # Translated into the ORM, and different queries are constructed for
        # expr and transformed_expr.
        #
        # The original expression compiles to the following SQL:
        #
        # SELECT "testapp_testobj"."id"
        # FROM "testapp_testobj"
        # INNER JOIN "testapp_testobj_m2ms"
        #       ON ("testapp_testobj"."id" = "testapp_testobj_m2ms"."testobj_id")
        # INNER JOIN "testapp_m2mmodel"
        #       ON ("testapp_testobj_m2ms"."m2mmodel_id" = "testapp_m2mmodel"."id")
        # WHERE ("testapp_m2mmodel"."int_value" = 10
        #        AND "testapp_m2mmodel"."char_value" = bar)
        #
        # The transformed version compiles to the following SQL, which is _not_
        # equivalent:
        #
        # SELECT "testapp_testobj"."id"
        # FROM "testapp_testobj"
        # WHERE NOT ((NOT ("testapp_testobj"."id" IN
        #                    (SELECT U1."testobj_id" AS Col1
        #                     FROM "testapp_testobj_m2ms" U1
        #                     INNER JOIN "testapp_m2mmodel" U2
        #                           ON (U1."m2mmodel_id" = U2."id")
        #                     WHERE U2."int_value" = 10))
        #             OR NOT ("testapp_testobj"."id" IN
        #                       (SELECT U1."testobj_id" AS Col1
        #                        FROM "testapp_testobj_m2ms" U1
        #                        INNER JOIN "testapp_m2mmodel" U2
        #                              ON (U1."m2mmodel_id" = U2."id")
        #                        WHERE U2."char_value" = bar))))

        # First show that these are not equivalent in the ORM, to verify that this
        # is not a bug in the predicate.P implementation.
        self.assertNotIn(
            self.test_obj,
            TestObj.objects.filter(Q(m2ms__int_value=10) & Q(m2ms__char_value='bar')))
        self.assertNotIn(
            self.test_obj,
            TestObj.objects.filter(expr))

        self.assertIn(
            self.test_obj,
            TestObj.objects.filter(~(~Q(m2ms__int_value=10) | ~Q(m2ms__char_value='bar'))))
        self.assertIn(
            self.test_obj,
            TestObj.objects.filter(transformed_expr))

        self.assertNotIn(self.test_obj, expr)
        self.assertIn(self.test_obj, transformed_expr)

        # Negate the queries, but weirdly, that doeesn't cause the answer to change.
        self._assert_P_matches_Q(
            self.test_obj,
            ~expr,
            ~(Q(m2ms__int_value=10) & Q(m2ms__char_value='bar')),
        )
        self.assertNotIn(
            self.test_obj,
            TestObj.objects.filter(~expr))

        # Test double negation still returns us to where we were originally.
        self._assert_P_matches_Q(
            self.test_obj,
            ~~expr,
            ~~(Q(m2ms__int_value=10) & Q(m2ms__char_value='bar'))),
        self.assertIn(
            self.test_obj,
            TestObj.objects.filter(~~expr))


class ComparisonFunctionsTest(TestCase):

    def setUp(self):
        self.date_obj = date(2016, 2, 16)
        self.datetime_obj = datetime(2016, 2, 16, 16, 24, 26, 688247)
        self.testobj = TestObj.objects.create(
            char_value="hello world",
            int_value=50,
            date_value=self.date_obj,
            datetime_value=self.datetime_obj,
        )

    def test_exact(self):
        self.assertTrue(OrmP(char_value__exact='hello world').eval(self.testobj))
        self.assertTrue(OrmP(char_value='hello world').eval(self.testobj))
        self.assertFalse(OrmP(char_value='hello worl').eval(self.testobj))

    def test_iexact(self):
        self.assertTrue(OrmP(char_value__iexact='heLLo World').eval(self.testobj))
        self.assertFalse(OrmP(char_value__iexact='hello worl').eval(self.testobj))

    def test_contains(self):
        self.assertTrue(OrmP(char_value__contains='hello').eval(self.testobj))
        self.assertFalse(OrmP(char_value__contains='foobar').eval(self.testobj))

    def test_icontains(self):
        self.assertTrue(OrmP(char_value__icontains='heLLo').eval(self.testobj))

    @skipIfDBFeature('has_case_insensitive_like')
    def test_case_sensitive_lookups_are_case_sensitive(self):
        self.assertFalse(OrmP(char_value='Hello world').eval(self.testobj))
        self.assertFalse(OrmP(char_value__contains='heLLo').eval(self.testobj))
        self.assertFalse(OrmP(char_value__startswith='Hello').eval(self.testobj))
        self.assertFalse(OrmP(char_value__endswith='World').eval(self.testobj))

    def test_gt(self):
        self.assertTrue(OrmP(int_value__gt=20).eval(self.testobj))
        self.assertFalse(OrmP(int_value__gt=80).eval(self.testobj))
        self.assertTrue(OrmP(int_value__gt=20.0).eval(self.testobj))
        self.assertFalse(OrmP(int_value__gt=80.0).eval(self.testobj))
        self.assertFalse(OrmP(int_value__gt=50).eval(self.testobj))

    def test_datetime_cast(self):
        """
        Tests that the Django ORM casting rules are obeyed in filtering by
        dates and times.
        """
        self.assertIn(
            self.testobj,
            OrmP(datetime_value__gt=self.date_obj - timedelta(days=1)))
        self.assertIn(
            self.testobj,
            OrmP(datetime_value__gte=self.date_obj - timedelta(days=1)))
        self.assertNotIn(
            self.testobj,
            OrmP(datetime_value__lte=self.date_obj - timedelta(days=1)))
        self.assertNotIn(
            self.testobj,
            OrmP(datetime_value__lt=self.date_obj - timedelta(days=1)))

        self.assertNotIn(
            self.testobj,
            OrmP(datetime_value__gt=self.date_obj + timedelta(days=1)))
        self.assertNotIn(
            self.testobj,
            OrmP(datetime_value__gte=self.date_obj + timedelta(days=1)))
        self.assertIn(
            self.testobj,
            OrmP(datetime_value__lte=self.date_obj + timedelta(days=1)))
        self.assertIn(
            self.testobj,
            OrmP(datetime_value__lt=self.date_obj + timedelta(days=1)))

        self.assertNotIn(
            self.testobj,
            OrmP(datetime_value__gt=self.datetime_obj + timedelta(seconds=1)))
        self.assertNotIn(
            self.testobj,
            OrmP(datetime_value__gte=self.datetime_obj + timedelta(seconds=1)))
        self.assertIn(
            self.testobj,
            OrmP(datetime_value__lte=self.datetime_obj + timedelta(seconds=1)))
        self.assertIn(
            self.testobj,
            OrmP(datetime_value__lt=self.datetime_obj + timedelta(seconds=1)))

        self.assertIn(
            self.testobj,
            OrmP(date_value__gt=self.datetime_obj - timedelta(days=1)))
        self.assertIn(
            self.testobj,
            OrmP(date_value__gte=self.datetime_obj - timedelta(days=1)))
        self.assertNotIn(
            self.testobj,
            OrmP(date_value__lte=self.datetime_obj - timedelta(days=1)))
        self.assertNotIn(
            self.testobj,
            OrmP(date_value__lt=self.datetime_obj - timedelta(days=1)))

        self.assertNotIn(
            self.testobj,
            OrmP(date_value__gt=self.datetime_obj + timedelta(days=1)))
        self.assertNotIn(
            self.testobj,
            OrmP(date_value__gte=self.datetime_obj + timedelta(days=1)))
        self.assertIn(
            self.testobj,
            OrmP(date_value__lte=self.datetime_obj + timedelta(days=1)))
        self.assertIn(
            self.testobj,
            OrmP(date_value__lt=self.datetime_obj + timedelta(days=1)))

    def test_gte(self):
        self.assertTrue(OrmP(int_value__gte=20).eval(self.testobj))
        self.assertTrue(OrmP(int_value__gte=50).eval(self.testobj))

    def test_lt(self):
        self.assertFalse(OrmP(int_value__lt=20).eval(self.testobj))
        self.assertTrue(OrmP(int_value__lt=80).eval(self.testobj))
        self.assertFalse(OrmP(int_value__lt=20.0).eval(self.testobj))
        self.assertTrue(OrmP(int_value__lt=80.0).eval(self.testobj))
        self.assertFalse(OrmP(int_value__lt=50).eval(self.testobj))

    def test_lte(self):
        self.assertFalse(OrmP(int_value__lte=20).eval(self.testobj))
        self.assertTrue(OrmP(int_value__lte=50).eval(self.testobj))

    def test_startswith(self):
        self.assertTrue(OrmP(char_value__startswith='hello').eval(self.testobj))
        self.assertFalse(OrmP(char_value__startswith='world').eval(self.testobj))

    def test_istartswith(self):
        self.assertTrue(OrmP(char_value__istartswith='heLLo').eval(self.testobj))
        self.assertFalse(OrmP(char_value__startswith='world').eval(self.testobj))

    def test_endswith(self):
        self.assertFalse(OrmP(char_value__endswith='hello').eval(self.testobj))
        self.assertTrue(OrmP(char_value__endswith='world').eval(self.testobj))

    def test_iendswith(self):
        self.assertFalse(OrmP(char_value__iendswith='hello').eval(self.testobj))
        self.assertTrue(OrmP(char_value__iendswith='World').eval(self.testobj))

    def test_dates(self):
        self.assertTrue(OrmP(date_value__year=self.date_obj.year).eval(self.testobj))
        self.assertTrue(OrmP(date_value__month=self.date_obj.month).eval(self.testobj))
        self.assertTrue(OrmP(date_value__day=self.date_obj.day).eval(self.testobj))

        orm_week_day = self.date_obj.isoweekday() % 7 + 1

        self.assertTrue(
            OrmP(date_value__week_day=orm_week_day).eval(self.testobj))

        self.assertFalse(OrmP(date_value__year=self.date_obj.year + 1).eval(self.testobj))
        self.assertFalse(OrmP(date_value__month=self.date_obj.month + 1).eval(self.testobj))
        self.assertFalse(OrmP(date_value__day=self.date_obj.day + 1).eval(self.testobj))
        self.assertFalse(P(date_value__week_day=orm_week_day + 1).eval(self.testobj))

    def test_null(self):
        self.assertTrue(OrmP(parent__isnull=True).eval(self.testobj))
        self.assertFalse(OrmP(parent__isnull=False).eval(self.testobj))

    def test_regex(self):
        self.assertTrue(OrmP(char_value__regex='hel*o').eval(self.testobj))
        self.assertFalse(OrmP(char_value__regex='Hel*o').eval(self.testobj))

    def test_iregex(self):
        self.assertTrue(OrmP(char_value__iregex='Hel*o').eval(self.testobj))

    def test_in_operator(self):
        p = OrmP(int_value__in=[50, 60])
        p2 = OrmP(int_value__in=[60, 70])
        self.assertTrue(self.testobj in p)
        self.assertFalse(self.testobj in p2)

    def test_pk_casting(self):
        pk_values_list = TestObj.objects.values_list('pk')
        self.assertIn(
            self.testobj, TestObj.objects.filter(pk__in=pk_values_list))
        self.assertIn(
            self.testobj, OrmP(pk__in=pk_values_list))

    def test_pk_casting_queryset(self):
        qs = TestObj.objects.all()
        self.assertIn(
            self.testobj, TestObj.objects.filter(pk__in=qs))
        self.assertIn(
            self.testobj, OrmP(pk__in=qs))

    def test_pk_casting_flat(self):
        pk_values_list = TestObj.objects.values_list('pk', flat=True)
        self.assertIn(
            self.testobj, TestObj.objects.filter(pk__in=pk_values_list))
        self.assertIn(
            self.testobj, OrmP(pk__in=pk_values_list))


class TestBooleanOperations(TestCase):

    def setUp(self):
        self.testobj = TestObj.objects.create(
            char_value="hello world",
            int_value=50,
            date_value=date.today())

    def test_and(self):
        p1 = OrmP(char_value__contains='hello')
        p2 = OrmP(int_value=50)
        p3 = OrmP(int_value__lt=20)
        pand1 = p1 & p2
        pand2 = p2 & p3
        self.assertTrue(pand1.eval(self.testobj))
        self.assertFalse(pand2.eval(self.testobj))

        self.assertNotIn(self.testobj, OrmP(int_value=20) & OrmP(int_value=50))

    def test_or(self):
        self.testobj.m2ms.create(int_value=10)
        p1 = OrmP(char_value__contains='hello', int_value=50)
        p2 = OrmP(int_value__gt=80)
        p3 = OrmP(int_value__lt=20)
        por1 = p1 | p2
        por2 = p2 | p3
        self.assertTrue(por1.eval(self.testobj))
        self.assertFalse(por2.eval(self.testobj))

        self.assertIn(self.testobj, OrmP(char_value='hello world') | OrmP(int_value=50))
        self.assertIn(self.testobj, OrmP(char_value='hello world') | ~OrmP(int_value=50))
        self.assertNotIn(self.testobj, ~(OrmP(char_value='hello world') | OrmP(int_value=50)))

        self.assertIn(self.testobj, OrmP(m2ms__int_value=10))
        self.assertIn(self.testobj, OrmP(char_value='hello world') | OrmP(m2ms__int_value=10))
        self.assertIn(self.testobj, OrmP(m2ms__int_value=10) | OrmP(char_value='hello world'))
        self.assertIn(self.testobj, OrmP(m2ms__int_value=10) | OrmP(char_value='something else'))
        self.assertIn(self.testobj, OrmP(char_value='something else') | OrmP(m2ms__int_value=10))

        self.assertIn(self.testobj, OrmP(int_value__in=[50, 20]))
        self.assertIn(self.testobj, OrmP(int_value=50) | OrmP(int_value=20))

    def test_not(self):
        self.assertIn(self.testobj, OrmP(int_value=self.testobj.int_value))
        self.assertNotIn(self.testobj, ~OrmP(int_value=self.testobj.int_value))

    def test_or2(self):
        p1 = P(foo=True)
        p2 = P(bar=False)
        d = {'foo': True, 'bar': True}
        self.assertIn(d, p1)
        self.assertNotIn(d, p2)
        self.assertIn(d, (p1 | p1))
        self.assertIn(d, (p1 | p2))
        self.assertIn(d, (p1 | p2))
        self.assertIn(d, (p2 | p1))
        self.assertNotIn(d, (p2 | p2))
        self.assertNotIn(d, (p2 | P(foo=False)))
        self.assertNotIn(d, (P(foo=False) | p2))


class TestLookupNode(TestCase):
    def test_lookup_parsing(self):
        self.assertEqual(
            LookupComponent.parse('foo__bar__in'),
            [LookupComponent('foo'), LookupComponent('bar'), LookupComponent('in')]
        )

    def _build_lookup_node_and_assert_invariants(self, lookups):
        """
        Builds a LookupNode from the given lookups, and asserts invariants for
        the class.
        """
        node = LookupNode(lookups=lookups)
        self.assertEqual(node.to_dict(), lookups)
        self.assertEqual(
            {lookup: node[lookup].value for lookup in lookups},
            lookups)
        return node

    def test_scalar(self):
        scalar = self._build_lookup_node_and_assert_invariants(
            {LookupComponent.EMPTY: 1})
        self.assertEqual(scalar.value, 1)

    def test_missing_lookup_raises_KeyError(self):
        node = self._build_lookup_node_and_assert_invariants({})
        with self.assertRaises(KeyError):
            node['foo']

    def test_nested_lookups(self):
        node = self._build_lookup_node_and_assert_invariants(dict(
            foo__bar__in=[1, 2],
            foo__bar__baz=6,
        ))
        self.assertEqual(list(node.children.keys()), [LookupComponent('foo')])
        self.assertEqual(node['foo']['bar']['in'].value, [1, 2])
        self.assertEqual(node['foo']['bar'].to_dict(), {'in': [1, 2], 'baz': 6})

    def assert_orm_invariant_for_lookup_node(self, node, obj):
        orm_values = (
            type(obj)._default_manager.filter(pk=obj.pk)
            .values(*node.to_dict().keys()))
        node_values = node.values(obj)

        def _make_hashable(d):
            return frozenset(d.items())

        self.assertEqual(
            set(map(_make_hashable, orm_values)),
            set(map(_make_hashable, node_values))
        )

    def test_lookup_node_values(self):
        test_obj = TestObj.objects.create()
        test_obj.m2ms.create(int_value=10, char_value='foo')
        test_obj.m2ms.create(int_value=20, char_value='bar')
        node = LookupNode(lookups=dict(
            m2ms__int_value=GET,
            m2ms__char_value=GET,
        ))
        self.assert_orm_invariant_for_lookup_node(node, test_obj)

    def test_lookup_node_multiple_values(self):
        node = self._build_lookup_node_and_assert_invariants(
            {'int_value': 50, 'int_value__lt': 20})
        self.assertEqual(node['int_value'].to_dict(), {'': 50, 'lt': 20})


class AttrClass(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class TestGetValuesList(TestCase):
    def get_values_list_and_assert_orm_invariants(self, obj, *args, **kwargs):
        """
        Gets the specified values list, and asserts that it matches the ORM
        behavior up to ordering.
        """
        queryset = type(obj)._default_manager.filter(pk=obj.pk)
        django_values_list = queryset.values_list(*args, **kwargs)
        values_list = get_values_list(obj, *args, **kwargs)
        self.assertEqual(set(values_list), set(django_values_list))
        return values_list

    def test_non_field_lookup_attribute(self):
        obj = AttrClass(a=AttrClass(c='x', d='y'), b=[1, 2])
        self.assertEqual(set(get_values_list(obj, 'a__c', 'b')), {('x', 1), ('x', 2)})
        self.assertEqual(set(get_values_list(obj, 'a__c', flat=True)), {'x'})

    def test_non_field_lookup_getitem(self):
        obj = dict(a=dict(c='x', d='y'), b=[1, 2])
        self.assertEqual(set(get_values_list(obj, 'a__c', 'b')), {('x', 1), ('x', 2)})
        self.assertEqual(set(get_values_list(obj, 'a__c', flat=True)), {'x'})

    def test_non_field_lookup_on_django_model(self):
        values_list = get_values_list(
            TestObj.objects.create(), 'some_property__x', flat=True)
        self.assertEqual(values_list, ['y'])

    def test_django_lookup(self):
        test_obj = TestObj.objects.create()
        test_obj.m2ms.create(int_value=10, char_value='foo')
        test_obj.m2ms.create(int_value=20, char_value='bar')
        values_list = self.get_values_list_and_assert_orm_invariants(
            test_obj, 'm2ms__int_value', 'm2ms__char_value')
        self.assertEqual(set(values_list), {(10, 'foo'), (20, 'bar')})

    def test_exceptions(self):
        with self.assertRaises(TypeError):
            get_values_list(object(), 'foo', 'bar', flat=True)
        with self.assertRaises(TypeError):
            get_values_list(object(), 'foo', something=None)
        with self.assertRaises(LookupNotFound):
            get_values_list(object(), 'foo')
        with self.assertRaises(LookupNotFound):
            get_values_list({}, 'foo')

    def test_reverse_one_to_one_relation(self):
        test_obj = TestObj.objects.create()
        with self.assertRaises(ObjectDoesNotExist):
            test_obj.onetoonemodel
        values_list = self.get_values_list_and_assert_orm_invariants(
            test_obj, 'onetoonemodel__pk', flat=True)
        self.assertEqual(values_list, [None])


class TestFilteringMethods(TestCase):
    def setUp(self):
        TestObj.objects.all().delete()
        self.obj1 = TestObj.objects.create(int_value=1)
        self.obj2 = TestObj.objects.create(int_value=2)
        self.objects = [self.obj1, self.obj2]

    def test_get_no_objects(self):
        predicate = OrmP(int_value=3)
        with self.assertRaises(ObjectDoesNotExist):
            TestObj.objects.get(predicate)
        with self.assertRaises(ObjectDoesNotExist):
            predicate.get(self.objects)

    def test_get_return_value(self):
        predicate = OrmP(int_value=1)
        self.assertEqual(TestObj.objects.get(predicate), self.obj1)
        self.assertEqual(predicate.get(self.objects), self.obj1)

    def test_get_multiple_objects(self):
        predicate = OrmP(int_value__in=[1, 2])
        with self.assertRaises(MultipleObjectsReturned):
            TestObj.objects.get(predicate)
        with self.assertRaises(MultipleObjectsReturned):
            predicate.get(self.objects)

    def test_filter(self):
        predicate = OrmP(int_value=3)
        self.assertEqual(set(TestObj.objects.filter(predicate)), set())
        self.assertEqual(set(predicate.filter(self.objects)), set())

        predicate = OrmP(int_value=1)
        self.assertEqual(set(TestObj.objects.filter(predicate)), {self.obj1})
        self.assertEqual(set(predicate.filter(self.objects)), {self.obj1})

        predicate = OrmP(int_value=2)
        self.assertEqual(set(TestObj.objects.filter(predicate)), {self.obj2})
        self.assertEqual(set(predicate.filter(self.objects)), {self.obj2})

        predicate = OrmP(int_value__in=[1, 2])
        self.assertEqual(
            set(TestObj.objects.filter(predicate)), {self.obj1, self.obj2})
        self.assertEqual(
            set(predicate.filter(self.objects)), {self.obj1, self.obj2})

    def test_exclude(self):
        predicate = OrmP(int_value=3)
        self.assertEqual(
            set(TestObj.objects.exclude(predicate)),
            {self.obj1, self.obj2})
        self.assertEqual(
            set(predicate.exclude(self.objects)),
            {self.obj1, self.obj2})

        predicate = OrmP(int_value=1)
        self.assertEqual(set(TestObj.objects.exclude(predicate)), {self.obj2})
        self.assertEqual(set(predicate.exclude(self.objects)), {self.obj2})

        predicate = OrmP(int_value=2)
        self.assertEqual(set(TestObj.objects.exclude(predicate)), {self.obj1})
        self.assertEqual(set(predicate.exclude(self.objects)), {self.obj1})

        predicate = OrmP(int_value__in=[1, 2])
        self.assertEqual(set(TestObj.objects.exclude(predicate)), set())
        self.assertEqual(set(predicate.exclude(self.objects)), set())

    def test_nested_q(self):
        predicate = OrmP(Q(int_value=1))
        self.assertEqual(set(TestObj.objects.filter(predicate)), {self.obj1})
        self.assertEqual(set(predicate.filter(self.objects)), {self.obj1})

        predicate = OrmP(Q(Q(int_value=1)))
        self.assertEqual(set(TestObj.objects.filter(predicate)), {self.obj1})
        self.assertEqual(set(predicate.filter(self.objects)), {self.obj1})


class TestDebugTools(TestCase):
    def setUp(self):
        self.test_obj = TestObj.objects.create(int_value=10)

    def test_debug_orm_validations(self):
        self.assertIn(self.test_obj, P(int_value=10))
        with mock.patch('predicate.debug.original_eval', return_value=False) as patched:
            with self.assertRaises(AssertionError):
                self.test_obj in OrmP(int_value=10)
        self.assertTrue(patched.called)

        with mock.patch('predicate.debug.original_eval', return_value=True) as patched:
            self.assertIn(self.test_obj, OrmP(int_value=10))
        self.assertTrue(patched.called)

    def test_patch_with_orm_eval(self):
        """
        Tests that the debug patch_with_orm_eval() context works as expected.
        """
        with mock.patch('predicate.debug.original_eval', return_value=False) as patched:
            self.assertIn(self.test_obj, P(int_value=10))
            self.assertFalse(patched.called)
            with patch_with_orm_eval():
                with self.assertRaises(AssertionError):
                    self.test_obj in P(int_value=10)
        self.assertTrue(patched.called)
        with patch_with_orm_eval():
            self.assertIn(self.test_obj, P(int_value=10))


class TestPredicateQuerySet(TestCase):
    """
    ``OrmPredicateQuerySet`` class wraps ``PredicateQuerySet`` and ``QuerySet``
    classes, and asserts they return the same values from public API methods.
    """
    def setUp(self):
        make_test_objects()

    def test_all(self):
        queryset = TestObj.objects.all()
        orm_pqs = OrmPredicateQuerySet(queryset)
        orm_pqs.all()

    def test_filter_all(self):
        queryset = TestObj.objects.filter(int_value__lt=50)
        orm_pqs = OrmPredicateQuerySet(queryset)
        orm_pqs.all()

    def test_filter(self):
        queryset = TestObj.objects.all()
        orm_pqs = OrmPredicateQuerySet(queryset)
        orm_pqs.filter(int_value__lt=50)

    def test_chain_filters(self):
        queryset = TestObj.objects.all()
        orm_pqs = OrmPredicateQuerySet(queryset)
        filtered = orm_pqs.filter(int_value=10, char_value='foo')
        filtered.filter(int_value__in=[1, 2])

    def test_exclude(self):
        queryset = TestObj.objects.all()
        orm_pqs = OrmPredicateQuerySet(queryset)
        orm_pqs.exclude(int_value__lt=50)
        orm_pqs.exclude(int_value=10, char_value='foo')

    def test_get(self):
        TestObj.objects.all().delete()
        TestObj.objects.create(int_value=1)
        TestObj.objects.create(int_value=2)
        orm_pqs = OrmPredicateQuerySet(TestObj.objects.all())

        with self.assertRaises(ObjectDoesNotExist):
            orm_pqs.get(int_value=3)
        with self.assertRaises(MultipleObjectsReturned):
            orm_pqs.get(int_value__lt=3)

        orm_pqs.get(int_value=1)
        orm_pqs.get(int_value=2)

    def test_exists(self):
        queryset = TestObj.objects.all()
        orm_pqs = OrmPredicateQuerySet(queryset)
        self.assertTrue(orm_pqs.exists())
        queryset = TestObj.objects.none()
        orm_pqs = OrmPredicateQuerySet(queryset)
        self.assertFalse(orm_pqs.exists())

    def test_count(self):
        queryset = TestObj.objects.all()
        orm_pqs = OrmPredicateQuerySet(queryset)
        orm_pqs.count()

    def assertResultsEqual(self, queryset, predicatequeryset):
        queryset._fetch_all()
        predicatequeryset._evaluate()

        def sort(iterable):
            return list(sorted(iterable, key=lambda obj: obj.id))

        self.assertListEqual(sort(queryset), sort(predicatequeryset))

    def test_or(self):
        qs1 = TestObj.objects.filter(int_value__lt=50)
        qs2 = TestObj.objects.filter(int_value__gte=50)
        merged_qs = qs1 | qs2
        pqs1 = PredicateQuerySet(qs1)
        pqs2 = PredicateQuerySet(qs2)
        merged_pqs = pqs1 | pqs2
        self.assertResultsEqual(merged_qs, merged_pqs)

        char_filter = {'char_value__icontains': 'red'}
        merged_qs = qs1.filter(**char_filter) | qs2.filter(**char_filter)
        merged_pqs = pqs1.filter(**char_filter) | pqs2.filter(**char_filter)
        self.assertResultsEqual(merged_qs, merged_pqs)

    def test_and(self):
        qs1 = TestObj.objects.filter(int_value__lt=50)
        qs2 = TestObj.objects.filter(int_value__gte=25)
        merged_qs = qs1 & qs2
        pqs1 = PredicateQuerySet(qs1)
        pqs2 = PredicateQuerySet(qs2)
        merged_pqs = pqs1 & pqs2
        self.assertResultsEqual(merged_qs, merged_pqs)

        char_filter = {'char_value__icontains': 'red'}
        merged_qs = qs1.filter(**char_filter) & qs2.filter(**char_filter)
        merged_pqs = pqs1.filter(**char_filter) & pqs2.filter(**char_filter)
        self.assertResultsEqual(merged_qs, merged_pqs)

    def test_getitem(self):
        qs = TestObj.objects.filter(int_value__lt=50)
        pqs = PredicateQuerySet(qs)
        self.assertEqual(qs.count(), pqs.count())
        for i in range(qs.count()):
            self.assertEqual(qs[i], pqs[i])
        for i in range(qs.count()):
            for j in range(i + 1, qs.count()):
                self.assertEqual(list(qs[i:j]), list(pqs[i:j]))
