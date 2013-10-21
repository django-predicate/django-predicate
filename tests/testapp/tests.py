from datetime import date
from random import choice, random

from django.db.models import Manager
from django.test import TestCase
from predicate import P

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
    def setUp(self):
        make_test_objects()

    def test_follow_relationship(self):
        p1 = P(parent__int_value__gt=10)
        obj = TestObj.objects.filter(parent__int_value__gt=10)[0]
        self.assertTrue(p1.eval(obj))
        p2 = P(parent__parent__int_value__gt=10)
        obj = TestObj.objects.filter(parent__parent__int_value__gt=10)[0]
        self.assertTrue(p2.eval(obj))

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


class GroupTest(TestCase):

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


class DictTest(TestCase):
    def test_from_dict(self):
        p = P.from_dict({
            'connector': P.AND,
            'negated': False,
            'children': [
                ['is_a_corgi', True],
                ['first_name__iexact', u'stumphrey'],
            ]
        })
        self.assertEqual(p.connector, P.AND)
        self.assertEqual(p.children[0], ['is_a_corgi', True])
        self.assertEqual(p.children[1], ['first_name__iexact', u'stumphrey'])

    def test_to_dict(self):
        p = P(is_a_corgi=True, first_name__iexact=u'stumphrey')
        p.negated = True
        p_as_dict = p.to_dict()
        children = p_as_dict.pop('children')
        self.assertEqual(p_as_dict, {'connector': P.AND, 'negated': True})
        self.assertEqual(set(children), set(p.children))
        p.connector = 'OR'
        self.assertEqual(p.to_dict()['connector'], P.OR)

    def test_match_exact(self):
        p = P(profile__is_a_corgi=True)
        self.assertTrue({'profile': {'is_a_corgi': True}} in p)

    def test_match_isnull(self):
        p = P(features__stumpers__isnull=True)
        self.assertTrue({} in p)
        self.assertTrue({'features': None} in p)
        self.assertTrue({'features': {'stumpers': None}} in p)
        self.assertTrue({'features': {'stumpers': False}} not in p)

    def test_match_multiple(self):
        p = P(is_a_corgi=True, first_name__iexact=u'stumphrey')
        self.assertTrue({'is_a_corgi': True, 'first_name': 'Stumphrey'} in p)
        self.assertFalse({'is_a_corgi': True, 'first_name': 'Corgnelius'} in p)

    def test_match_index(self):
        p = P(favorites__0__iexact=u'frisking')
        self.assertTrue({'favorites': ['frisking', 'walks']} in p)
        self.assertTrue({'favorites': ['vet visits']} not in p)

    def test_match_in(self):
        p = P(favorites__in=['frisking', 'walks'])
        self.assertTrue({'favorites': ['frisking', 'walks', 'kibble']} in p)
        self.assertTrue({'favorites': ['frisking', 'walks']} in p)
        self.assertTrue({'favorites': ['frisking']} in p)
        self.assertTrue({'favorites': ['vet visits']} not in p)

    def test_match_any(self):
        p = P(favorites__any=u'frisking')
        self.assertTrue({'favorites': ['walks', 'frisking', 'kibble']} in p)

    def test_lookup_ambiguous_year_attr(self):
        p = P(start_date__year__exact=1994)
        self.assertTrue({'start_date': {'year': 1994}} in p)

    def test_match_attr_in(self):
        p = P(favorites__slug__in=['frisking', 'walks'])
        self.assertTrue({
            'favorites': [
                {'slug': 'frisking'},
                {'slug': 'walks'},
                {'slug': 'kibble'},
            ]
        } in p)
        self.assertTrue({
            'favorites': [
                {'slug': 'frisking'},
                {'slug': 'walks'},
            ]
        } in p)
        self.assertTrue({'favorites': [{'slug': 'frisking'}]} in p)
        self.assertTrue({'favorites': [{'slug': 'vet visits'}]} not in p)

    def test_empty_predicate(self):
        self.assertTrue({} in P())
        self.assertTrue({'name': 'Mr. Corgsly'} in P())

    def test_combination(self):
        p1 = P(is_member=True) | P(addresses__city__iexact=u'austin')
        self.assertEqual(p1.connector, 'OR')
        p2 = P(attended_festival=True)
        p_combined = p1 & p2
        self.assertEqual(p_combined.connector, 'AND')
        self.assertEqual(p_combined, p2 & p1)


class M2MTest(TestCase):
    def test_match_m2m_in(self):
        p = P(favorites__slug__in=['frisking', 'walks'])
        favorites = Manager()
        o = {"favorites": favorites}
        favorites.values_list = lambda *a, **k: ['frisking', 'walks', 'kibble']
        self.assertTrue(o in p)
        favorites.values_list = lambda *a, **k: ['frisking', 'walks']
        self.assertTrue(o in p)
        favorites.values_list = lambda *a, **k: ['frisking']
        self.assertTrue(o in p)
        favorites.values_list = lambda *a, **k: ['vet visits']
        self.assertTrue(o not in p)

    def test_match_m2m_index(self):
        p = P(favorites__0__slug=u'frisking')
        favorites = Manager()
        o = {"favorites": favorites}
        favorites.all = lambda: [{'slug': 'frisking'}, {'slug': 'walks'}]
        self.assertTrue(o in p)
        favorites.all = lambda: [{'slug': 'vet visits'}]
        self.assertTrue(o not in p)
