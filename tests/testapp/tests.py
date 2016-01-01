from datetime import date
from datetime import datetime
from datetime import timedelta
from random import choice, random
from unittest import expectedFailure

from django.test import skipIfDBFeature
from django.test import TestCase
from nose.tools import assert_equal

from predicate.predicate import GET
from predicate.predicate import LookupComponent
from predicate.predicate import LookupNode
from predicate import P
from models import CustomRelatedNameOneToOneModel
from models import ForeignKeyModel
from models import M2MModel
from models import OneToOneModel
from models import TestObj

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


class OrmP(P):
    """
    Implementation of P semantics that asserts the ORM and P have the same
    semantics.
    """
    def eval(self, instance):
        queryset = type(instance)._default_manager.filter(self, pk=instance.pk)
        orm_value = queryset.exists()
        super_value = super(OrmP, self).eval(instance)
        assert_equal(orm_value, super_value)
        return super_value


def assert_universal_invariants(predicate, instance):
    """
    Asserts fundamental invariants that should always hold:
    - The predicate should match the instance iff the ORM backend matches the
      instance.
    - Negation of the predicate should negate membership.
    """
    queryset = type(instance)._default_manager.filter(predicate,
                                                      pk=instance.pk)
    assert_equal(instance in predicate, queryset.exists())
    assert_equal(instance in predicate, not(instance in ~predicate))


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
        assert_universal_invariants(OrmP(children__int_value=2), parent)

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

    def test_joint_conditions(self):
        """
        Test that joint conditions must be on the same aliased instance.

        In particular P(rel__attr1=val1, rel__attr2=val2) produces only a
        single join, so the two conditions must be jointly satisfied on the
        same database row.
        """
        test_obj = TestObj.objects.create()
        test_obj.m2ms.create(int_value=10, char_value='foo')
        test_obj.m2ms.create(int_value=20, char_value='bar')

        self.assertNotIn(
            test_obj,
            TestObj.objects.filter(m2ms__int_value=10, m2ms__char_value='bar'))
        self.assertIn(
            test_obj,
            TestObj.objects.filter(m2ms__int_value=10, m2ms__char_value='foo'))

        self.assertNotIn(
            test_obj,
            OrmP(m2ms__int_value=10, m2ms__char_value='bar'))
        self.assertIn(
            test_obj,
            OrmP(m2ms__int_value=10, m2ms__char_value='foo'))


class ComparisonFunctionsTest(TestCase):

    def setUp(self):
        self.testobj = TestObj.objects.create(
            char_value="hello world",
            int_value=50,
            date_value=date.today(),
            datetime_value=datetime.now(),
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

    @expectedFailure  # FIXME: fix datetime casting bugs.
    def test_datetime_cast(self):
        """
        Tests that the Django ORM casting rules are obeyed in filtering by
        dates and times.
        """
        today = date.today()
        now = datetime.now()
        self.assertIn(
            self.testobj,
            OrmP(datetime_value__gt=today - timedelta(days=1)))
        self.assertIn(
            self.testobj,
            OrmP(datetime_value__gte=today - timedelta(days=1)))
        self.assertNotIn(
            self.testobj,
            OrmP(datetime_value__lte=today - timedelta(days=1)))
        self.assertNotIn(
            self.testobj,
            OrmP(datetime_value__lt=today - timedelta(days=1)))

        self.assertNotIn(
            self.testobj,
            OrmP(datetime_value__gt=today + timedelta(days=1)))
        self.assertNotIn(
            self.testobj,
            OrmP(datetime_value__gte=today + timedelta(days=1)))
        self.assertIn(
            self.testobj,
            OrmP(datetime_value__lte=today + timedelta(days=1)))
        self.assertIn(
            self.testobj,
            OrmP(datetime_value__lt=today + timedelta(days=1)))

        self.assertIn(
            self.testobj,
            OrmP(date_value__gt=now - timedelta(days=1)))
        self.assertIn(
            self.testobj,
            OrmP(date_value__gte=now - timedelta(days=1)))
        self.assertNotIn(
            self.testobj,
            OrmP(date_value__lte=now - timedelta(days=1)))
        self.assertNotIn(
            self.testobj,
            OrmP(date_value__lt=now - timedelta(days=1)))

        self.assertNotIn(
            self.testobj,
            OrmP(date_value__gt=now + timedelta(days=1)))
        self.assertNotIn(
            self.testobj,
            OrmP(date_value__gte=now + timedelta(days=1)))
        self.assertIn(
            self.testobj,
            OrmP(date_value__lte=now + timedelta(days=1)))
        self.assertIn(
            self.testobj,
            OrmP(date_value__lt=now + timedelta(days=1)))

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
        today = date.today()
        self.assertTrue(OrmP(date_value__year=today.year).eval(self.testobj))
        self.assertTrue(OrmP(date_value__month=today.month).eval(self.testobj))
        self.assertTrue(OrmP(date_value__day=today.day).eval(self.testobj))

        orm_week_day = today.isoweekday() % 7 + 1

        self.assertTrue(
            OrmP(date_value__week_day=orm_week_day).eval(self.testobj))

        self.assertFalse(OrmP(date_value__year=today.year + 1).eval(self.testobj))
        self.assertFalse(OrmP(date_value__month=today.month + 1).eval(self.testobj))
        self.assertFalse(OrmP(date_value__day=today.day + 1).eval(self.testobj))
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

    # FIXME: FieldDoesNotExist: TestObj has no field named 'pk'
    @expectedFailure
    def test_pk_casting(self):
        pk_values_list = TestObj.objects.values_list('pk')
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

    def test_or(self):
        p1 = OrmP(char_value__contains='hello', int_value=50)
        p2 = OrmP(int_value__gt=80)
        p3 = OrmP(int_value__lt=20)
        por1 = p1 | p2
        por2 = p2 | p3
        self.assertTrue(por1.eval(self.testobj))
        self.assertFalse(por2.eval(self.testobj))

    def test_not(self):
        self.assertIn(self.testobj, OrmP(int_value=self.testobj.int_value))
        self.assertNotIn(self.testobj, ~OrmP(int_value=self.testobj.int_value))


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
        self.assertEqual(node.children.keys(), [LookupComponent('foo')])
        self.assertEqual(node['foo']['bar']['in'].value, [1, 2])
        self.assertEqual(node['foo']['bar'].to_dict(), {'in': [1, 2], 'baz': 6})

    def assert_orm_invariant_for_lookup_node(self, node, obj):
        orm_values = (
            type(obj)._default_manager.filter(pk=obj.pk)
            .values(*node.to_dict().keys()))
        node_values = node.values(obj)

        def _make_hashable(d):
            return frozenset(d.iteritems())

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
