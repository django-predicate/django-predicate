from datetime import date
from random import choice, random

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



class SimpleTest(TestCase):
    def test_basic_addition(self):
        """
        Tests that 1 + 1 always equals 2.
        """
        self.assertEqual(1 + 1, 2)

    def test_simple_predicate(self):
        test_o = TestObj(char_value="hello")

        p = P(char_value__exact="hello")
        self.assertTrue(p.eval(test_o))

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

    def test_contains(self):
        self.assertTrue(P(char_value__contains='hello').eval(self.testobj))
        self.assertFalse(P(char_value__contains='foobar').eval(self.testobj))

    def test_icontains(self):
        self.assertTrue(P(char_value__icontains='heLLo').eval(self.testobj))
