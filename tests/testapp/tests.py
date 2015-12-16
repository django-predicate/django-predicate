from datetime import date
from random import choice, random

from django.test import TestCase
from nose.tools import assert_equal

from predicate import P
from predicate.predicate import LookupExpression
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
        p1 = P(parent__int_value__gt=10)
        obj = TestObj.objects.filter(parent__int_value__gt=10)[0]
        self.assertTrue(p1.eval(obj))
        p2 = P(parent__parent__int_value__gt=10)
        obj = TestObj.objects.filter(parent__parent__int_value__gt=10)[0]
        self.assertTrue(p2.eval(obj))

    def test_children_relationship_single(self):
        parent = TestObj.objects.create(int_value=100)
        TestObj.objects.bulk_create([
            TestObj(int_value=i, parent=parent) for i in range(3)
        ])
        self.assertIn(parent, TestObj.objects.filter(P(children__int_value=2)))
        pred = P(children__int_value=2)
        pred.foo = True
        self.assertIn(parent, pred)
        assert_universal_invariants(P(children__int_value=2), parent)


class TestLookupExpression(TestCase):
    def test_get_field_on_reverse_foreign_key(self):
        parent = TestObj.objects.create(int_value=100)
        TestObj.objects.bulk_create([
            TestObj(int_value=i, parent=parent) for i in range(3)
        ])
        expr = LookupExpression(('children__int_value', 2))
        lookup_model, lookup_field, lookup_type = expr.get_field(parent)
        self.assertEqual(set(lookup_field), set(range(3)))


class ComparisonFunctionsTest(TestCase):

    def setUp(self):
        self.testobj = TestObj(
                char_value="hello world",
                int_value=50,
                date_value=date.today())

    def test_exact(self):
        self.assertTrue(P(char_value__exact='hello world').eval(self.testobj))
        self.assertTrue(P(char_value='hello world').eval(self.testobj))
        self.assertFalse(P(char_value='Hello world').eval(self.testobj))
        self.assertFalse(P(char_value='hello worl').eval(self.testobj))

    def test_iexact(self):
        self.assertTrue(P(char_value__iexact='heLLo World').eval(self.testobj))
        self.assertFalse(P(char_value__iexact='hello worl').eval(self.testobj))

    def test_contains(self):
        self.assertTrue(P(char_value__contains='hello').eval(self.testobj))
        self.assertFalse(P(char_value__contains='foobar').eval(self.testobj))

    def test_icontains(self):
        self.assertTrue(P(char_value__icontains='heLLo').eval(self.testobj))

    def test_gt(self):
        self.assertTrue(P(int_value__gt=20).eval(self.testobj))
        self.assertFalse(P(int_value__gt=80).eval(self.testobj))
        self.assertTrue(P(int_value__gt=20.0).eval(self.testobj))
        self.assertFalse(P(int_value__gt=80.0).eval(self.testobj))
        self.assertFalse(P(int_value__gt=50).eval(self.testobj))

    def test_gte(self):
        self.assertTrue(P(int_value__gte=20).eval(self.testobj))
        self.assertTrue(P(int_value__gte=50).eval(self.testobj))

    def test_lt(self):
        self.assertFalse(P(int_value__lt=20).eval(self.testobj))
        self.assertTrue(P(int_value__lt=80).eval(self.testobj))
        self.assertFalse(P(int_value__lt=20.0).eval(self.testobj))
        self.assertTrue(P(int_value__lt=80.0).eval(self.testobj))
        self.assertFalse(P(int_value__lt=50).eval(self.testobj))

    def test_lte(self):
        self.assertFalse(P(int_value__lte=20).eval(self.testobj))
        self.assertTrue(P(int_value__lte=50).eval(self.testobj))

    def test_startswith(self):
        self.assertTrue(P(char_value__startswith='hello').eval(self.testobj))
        self.assertFalse(P(char_value__startswith='world').eval(self.testobj))
        self.assertFalse(P(char_value__startswith='Hello').eval(self.testobj))

    def test_istartswith(self):
        self.assertTrue(P(char_value__istartswith='heLLo').eval(self.testobj))
        self.assertFalse(P(char_value__startswith='world').eval(self.testobj))

    def test_endswith(self):
        self.assertFalse(P(char_value__endswith='hello').eval(self.testobj))
        self.assertTrue(P(char_value__endswith='world').eval(self.testobj))
        self.assertFalse(P(char_value__endswith='World').eval(self.testobj))

    def test_iendswith(self):
        self.assertFalse(P(char_value__iendswith='hello').eval(self.testobj))
        self.assertTrue(P(char_value__iendswith='World').eval(self.testobj))

    def test_dates(self):
        today = date.today()
        self.assertTrue(P(date_value__year=today.year).eval(self.testobj))
        self.assertTrue(P(date_value__month=today.month).eval(self.testobj))
        self.assertTrue(P(date_value__day=today.day).eval(self.testobj))
        self.assertTrue(P(date_value__week_day=today.weekday()).eval(self.testobj))

        self.assertFalse(P(date_value__year=today.year + 1).eval(self.testobj))
        self.assertFalse(P(date_value__month=today.month + 1).eval(self.testobj))
        self.assertFalse(P(date_value__day=today.day + 1).eval(self.testobj))
        self.assertFalse(P(date_value__week_day=today.weekday() + 1).eval(self.testobj))

    def test_null(self):
        self.assertTrue(P(parent__isnull=True).eval(self.testobj))
        self.assertFalse(P(parent__isnull=False).eval(self.testobj))

    def test_regex(self):
        self.assertTrue(P(char_value__regex='hel*o').eval(self.testobj))
        self.assertFalse(P(char_value__regex='Hel*o').eval(self.testobj))

    def test_iregex(self):
        self.assertTrue(P(char_value__iregex='Hel*o').eval(self.testobj))

    def test_in_operator(self):
        p = P(int_value__lte=50)
        p2 = P(int_value__lt=10)
        self.assertTrue(self.testobj in p)
        self.assertFalse(self.testobj in p2)


class TestBooleanOperations(TestCase):

    def setUp(self):
        self.testobj = TestObj(
                char_value="hello world",
                int_value=50,
                date_value=date.today())

    def test_and(self):
        p1 = P(char_value__contains='hello')
        p2 = P(int_value=50)
        p3 = P(int_value__lt=20)
        pand1 = p1 & p2
        pand2 = p2 & p3
        self.assertTrue(pand1.eval(self.testobj))
        self.assertFalse(pand2.eval(self.testobj))

    def test_or(self):
        p1 = P(char_value__contains='hello', int_value=50)
        p2 = P(int_value__gt=80)
        p3 = P(int_value__lt=20)
        por1 = p1 | p2
        por2 = p2 | p3
        self.assertTrue(por1.eval(self.testobj))
        self.assertFalse(por2.eval(self.testobj))

    def test_not(self):
        self.assertIn(self.testobj, P(int_value=self.testobj.int_value))
        self.assertNotIn(self.testobj, ~P(int_value=self.testobj.int_value))
